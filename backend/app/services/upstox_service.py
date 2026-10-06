"""Upstox API v2 — credentials, OAuth and the candle fetch Check Trades uses.

Endpoints are v2, taken from Upstox's own documentation rather than memory:

    authorize  GET  https://api.upstox.com/v2/login/authorization/dialog
                    ?client_id=&redirect_uri=&response_type=code
    token      POST https://api.upstox.com/v2/login/authorization/token
                    form: code, client_id, client_secret, redirect_uri,
                          grant_type=authorization_code
                    headers: accept: application/json,
                             Content-Type: application/x-www-form-urlencoded
    candles    GET  /v2/historical-candle/{key}/{interval}/{to}/{from}
               GET  /v2/historical-candle/intraday/{key}/{interval}

A candle is a seven-element array: [ts, open, high, low, close, volume, oi].
1-minute candles are kept for six months, which comfortably covers the two
days of ticks Check Trades can look at.

The access token expires daily. Nothing here tries to be clever about that:
a failed call marks the row disconnected and the operator reconnects, which
is one click and is honest about what happened.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.models.upstox_settings import UpstoxSettings
from app.utils.crypto import decrypt, encrypt
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

API_BASE = "https://api.upstox.com/v2"
AUTH_DIALOG = f"{API_BASE}/login/authorization/dialog"
TOKEN_URL = f"{API_BASE}/login/authorization/token"

#: Upstox is a third party on the far side of the internet. Every call here
#: is a diagnostic, never on an order path, so a slow answer should give up
#: rather than hold a request open.
_TIMEOUT = 15.0


async def get_settings() -> UpstoxSettings:
    """The singleton row, created on first read so the admin page always has
    something to render (with the redirect URL already filled in)."""
    row = await UpstoxSettings.find_one({})
    if row is None:
        row = UpstoxSettings()
        await row.insert()
    return row


def _secret_of(row: UpstoxSettings) -> str:
    if not row.encrypted_api_secret or not row.encrypted_api_secret_iv:
        return ""
    try:
        return decrypt(row.encrypted_api_secret, row.encrypted_api_secret_iv)
    except Exception:  # noqa: BLE001 — a key rotation must not 500 the page
        logger.exception("upstox_secret_decrypt_failed")
        return ""


async def save_credentials(
    *, api_key: str | None = None, api_secret: str | None = None,
    redirect_url: str | None = None, enabled: bool | None = None,
) -> UpstoxSettings:
    """Store what the operator typed. Only fields actually supplied change,
    so saving the key does not wipe a secret that is already there — the UI
    never sends the secret back, and a blanket write would erase it."""
    row = await get_settings()
    if api_key is not None:
        row.api_key = api_key.strip()
    if api_secret:
        # Whitespace from a copy-paste is the single most common reason an
        # exchange is refused, and the error Upstox returns does not say so.
        ct, iv = encrypt(api_secret.strip())
        row.encrypted_api_secret = ct
        row.encrypted_api_secret_iv = iv
    if redirect_url is not None:
        row.redirect_url = redirect_url.strip()
    if enabled is not None:
        row.enabled = bool(enabled)
    await row.save()
    return row


async def login_url(state: str = "stockex") -> str:
    """The page the operator opens to authorise the app."""
    row = await get_settings()
    if not row.api_key:
        raise ValueError("Set the Upstox API key first.")
    q = urlencode({
        "client_id": row.api_key,
        "redirect_uri": row.redirect_url,
        "response_type": "code",
        "state": state,
    })
    return f"{AUTH_DIALOG}?{q}"


async def exchange_code(code: str) -> UpstoxSettings:
    """Swap the one-time code for an access token.

    `redirect_uri` has to be sent again and has to be identical to the one
    the dialog was opened with AND to the one registered on the Upstox app;
    Upstox refuses the exchange otherwise, which is why the UI shows that URL
    to copy rather than inviting anyone to retype it.
    """
    row = await get_settings()
    secret = _secret_of(row)
    if not row.api_key or not secret:
        raise ValueError("Upstox API key and secret must both be saved first.")

    form = {
        "code": code,
        "client_id": row.api_key,
        "client_secret": secret,
        "redirect_uri": row.redirect_url,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                TOKEN_URL,
                data=form,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        body: dict[str, Any] = r.json() if r.content else {}
    except Exception as e:  # noqa: BLE001
        row.is_connected = False
        row.last_error = f"Could not reach Upstox: {e}"
        await row.save()
        raise

    token = body.get("access_token")
    if not token:
        # Upstox puts the useful part in `errors[].message`; surface it as-is
        # rather than a generic failure the operator cannot act on.
        detail = body.get("errors") or body.get("message") or r.text[:300]
        row.is_connected = False
        row.last_error = str(detail)[:500]
        await row.save()
        raise ValueError(f"Upstox refused the login: {detail}")

    row.access_token = token
    row.is_connected = True
    row.last_connected = now_utc()
    row.last_error = None
    await row.save()
    logger.info("upstox_connected")
    return row


async def disconnect() -> UpstoxSettings:
    """Forget the session, keep the credentials. Reconnecting is then one
    click rather than a retype of the secret."""
    row = await get_settings()
    row.access_token = None
    row.is_connected = False
    row.token_expiry = None
    await row.save()
    return row


async def status() -> dict[str, Any]:
    """What the admin page renders. The secret is never returned — only
    whether one is stored."""
    row = await get_settings()
    return {
        "api_key": row.api_key,
        "has_secret": bool(row.encrypted_api_secret),
        "redirect_url": row.redirect_url,
        "connected": bool(row.is_connected and row.access_token),
        "enabled": bool(row.enabled),
        "last_connected": row.last_connected,
        "last_error": row.last_error,
    }


# ── Market data ───────────────────────────────────────────────────────
async def _get(path: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(
            f"{API_BASE}{path}",
            headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
        )
    return r.json() if r.content else {}


async def minute_candles(
    instrument_key: str, on: date, *, to: date | None = None
) -> list[list[Any]]:
    """1-minute candles for `instrument_key`, newest-first as Upstox returns
    them. Each is [ts, open, high, low, close, volume, oi].

    Returns an empty list rather than raising when the session is not
    connected or Upstox says nothing — a verification source that cannot
    answer should make the check say "no second opinion", not fail the whole
    report.
    """
    row = await get_settings()
    if not (row.enabled and row.is_connected and row.access_token):
        return []
    to_d = (to or on).isoformat()
    path = f"/historical-candle/{instrument_key}/1minute/{to_d}/{on.isoformat()}"
    try:
        body = await _get(path, row.access_token)
    except Exception:  # noqa: BLE001
        logger.warning("upstox_candles_failed key=%s", instrument_key, exc_info=True)
        return []
    if str(body.get("status")) != "success":
        # A dead token looks exactly like this, so record it where the admin
        # page can show it instead of leaving the operator guessing.
        detail = body.get("errors") or body.get("message")
        if detail:
            row.last_error = str(detail)[:500]
            row.is_connected = False
            await row.save()
        return []
    return list(((body.get("data") or {}).get("candles")) or [])


def candle_at(candles: list[list[Any]], minute_iso: str) -> list[Any] | None:
    """The candle whose timestamp starts with `minute_iso` (YYYY-MM-DDTHH:MM).

    Upstox stamps each candle with the START of its minute and returns them
    newest-first; matching on the prefix sidesteps the trailing offset
    (+05:30) and the seconds, which are always zero but not always written
    the same way.
    """
    for c in candles or []:
        if c and str(c[0]).startswith(minute_iso):
            return c
    return None


def _dt_minute(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")
