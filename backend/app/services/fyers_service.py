"""Fyers API v3 — credentials, login, and the quote call the price check uses.

Endpoints (Fyers API v3 documentation):

    login    GET  https://api-t1.fyers.in/api/v3/generate-authcode
                  ?client_id=&redirect_uri=&response_type=code&state=
             → browser comes back to redirect_uri with ?auth_code=&state=
    token    POST https://api-t1.fyers.in/api/v3/validate-authcode
                  json: grant_type=authorization_code,
                        appIdHash=sha256("<app_id>:<secret>"), code
    quotes   GET  https://api-t1.fyers.in/data/quotes?symbols=NSE:SBIN-EQ
                  header  Authorization: <app_id>:<access_token>
             → {"s":"ok","d":[{"n":..,"s":"ok","v":{"lp":..,"bid":..,"ask":..}}]}

The access token expires daily. As with Upstox, nothing here tries to be
clever about it: a failed call marks the row disconnected and the operator
clicks Connect again.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.models.fyers_settings import FyersSettings
from app.utils.crypto import decrypt, encrypt
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

API_BASE = "https://api-t1.fyers.in/api/v3"
DATA_BASE = "https://api-t1.fyers.in/data"
AUTH_URL = f"{API_BASE}/generate-authcode"
TOKEN_URL = f"{API_BASE}/validate-authcode"

#: Login calls are a human clicking a button; they can afford to wait.
_LOGIN_TIMEOUT = 15.0
#: Quote calls run in the background beside a live order. An answer that
#: arrives this late no longer describes the moment the order was placed.
QUOTE_TIMEOUT_SEC = 1.5

#: Fyers error codes that mean the token is gone (expired / revoked /
#: invalid). Any of these flips the row to disconnected so the admin card
#: says so instead of every check failing silently.
_DEAD_TOKEN_CODES = {-8, -15, -16, -17}

#: The settings row is read on every market order; keep it in memory briefly
#: instead of a Mongo read per order.
_SETTINGS_TTL_SEC = 15.0
_cache: dict[str, tuple[float, FyersSettings]] = {}


async def get_settings(*, fresh: bool = False) -> FyersSettings:
    """The singleton row, created on first read so the admin page always has
    something to render (with the redirect URL already filled in)."""
    hit = _cache.get("row")
    if not fresh and hit and (time.monotonic() - hit[0]) < _SETTINGS_TTL_SEC:
        return hit[1]
    row = await FyersSettings.find_one({})
    if row is None:
        row = FyersSettings()
        await row.insert()
    _cache["row"] = (time.monotonic(), row)
    return row


async def _save(row: FyersSettings) -> None:
    await row.save()
    _cache["row"] = (time.monotonic(), row)


def _secret_of(row: FyersSettings) -> str:
    if not row.encrypted_secret or not row.encrypted_secret_iv:
        return ""
    try:
        return decrypt(row.encrypted_secret, row.encrypted_secret_iv)
    except Exception:  # noqa: BLE001 — a key rotation must not 500 the page
        logger.exception("fyers_secret_decrypt_failed")
        return ""


async def save_credentials(
    *, app_id: str | None = None, secret: str | None = None,
    redirect_url: str | None = None, enabled: bool | None = None,
) -> FyersSettings:
    """Store what the operator typed. Only supplied fields change, so saving
    the app id does not wipe a secret that is already stored — the UI never
    sends the secret back."""
    row = await get_settings(fresh=True)
    if app_id is not None:
        row.app_id = app_id.strip()
    if secret:
        ct, iv = encrypt(secret.strip())
        row.encrypted_secret = ct
        row.encrypted_secret_iv = iv
    if redirect_url is not None:
        row.redirect_url = redirect_url.strip()
    if enabled is not None:
        row.enabled = bool(enabled)
    await _save(row)
    return row


async def login_url(state: str = "stockex") -> str:
    row = await get_settings(fresh=True)
    if not row.app_id:
        raise ValueError("Set the Fyers App ID first.")
    q = urlencode({
        "client_id": row.app_id,
        "redirect_uri": row.redirect_url,
        "response_type": "code",
        "state": state,
    })
    return f"{AUTH_URL}?{q}"


async def exchange_code(auth_code: str) -> FyersSettings:
    """Swap the one-time auth code for the day's access token."""
    row = await get_settings(fresh=True)
    secret = _secret_of(row)
    if not row.app_id or not secret:
        raise ValueError("Fyers App ID and secret must both be saved first.")

    app_id_hash = hashlib.sha256(f"{row.app_id}:{secret}".encode()).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=_LOGIN_TIMEOUT) as c:
            r = await c.post(
                TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "appIdHash": app_id_hash,
                    "code": auth_code,
                },
            )
        body: dict[str, Any] = r.json() if r.content else {}
    except Exception as e:  # noqa: BLE001
        row.is_connected = False
        row.last_error = f"Could not reach Fyers: {e}"
        await _save(row)
        raise

    token = body.get("access_token")
    if not token:
        detail = body.get("message") or body.get("s") or r.text[:300]
        row.is_connected = False
        row.last_error = str(detail)[:500]
        await _save(row)
        raise ValueError(f"Fyers refused the login: {detail}")

    row.access_token = token
    row.is_connected = True
    row.last_connected = now_utc()
    row.last_error = None
    await _save(row)
    logger.info("fyers_connected")
    return row


async def disconnect() -> FyersSettings:
    """Forget the session, keep the credentials."""
    row = await get_settings(fresh=True)
    row.access_token = None
    row.is_connected = False
    await _save(row)
    return row


async def status() -> dict[str, Any]:
    """What the admin card renders. The secret is never returned."""
    row = await get_settings(fresh=True)
    return {
        "app_id": row.app_id,
        "has_secret": bool(row.encrypted_secret),
        "redirect_url": row.redirect_url,
        "connected": bool(row.is_connected and row.access_token),
        "enabled": bool(row.enabled),
        "last_connected": row.last_connected,
        "last_error": row.last_error,
    }


# ── Quotes ────────────────────────────────────────────────────────────
@dataclass
class FyersQuote:
    ltp: Decimal | None
    bid: Decimal | None
    ask: Decimal | None


class FyersUnavailableError(Exception):
    """Fyers could not answer. The message is shown on the check row."""


def _price(v: Any) -> Decimal | None:
    # The I/O boundary: Fyers sends floats; nothing past here sees one.
    try:
        d = to_decimal(v)
    except Exception:  # noqa: BLE001
        return None
    return d if d > 0 else None


async def get_quote(fyers_symbol: str) -> FyersQuote:
    """Live quote for one Fyers symbol, e.g. "NSE:NIFTY26NOVFUT".

    Raises FyersUnavailableError with a readable reason when there is no answer.
    """
    row = await get_settings()
    if not (row.is_connected and row.access_token and row.app_id):
        raise FyersUnavailableError("Fyers not connected")
    try:
        async with httpx.AsyncClient(timeout=QUOTE_TIMEOUT_SEC) as c:
            r = await c.get(
                f"{DATA_BASE}/quotes",
                params={"symbols": fyers_symbol},
                headers={"Authorization": f"{row.app_id}:{row.access_token}"},
            )
        body: dict[str, Any] = r.json() if r.content else {}
    except httpx.TimeoutException as e:
        raise FyersUnavailableError("Fyers timeout") from e
    except Exception as e:  # noqa: BLE001
        raise FyersUnavailableError(f"Fyers error: {e}"[:200]) from e

    if body.get("s") != "ok":
        code = body.get("code")
        msg = str(body.get("message") or body.get("s") or r.status_code)[:200]
        if isinstance(code, int) and code in _DEAD_TOKEN_CODES:
            fresh = await get_settings(fresh=True)
            fresh.is_connected = False
            fresh.last_error = f"Session expired: {msg}"
            await _save(fresh)
            raise FyersUnavailableError("Fyers session expired")
        if r.status_code == 429 or code == 429:
            raise FyersUnavailableError("Fyers rate limit")
        raise FyersUnavailableError(f"Fyers error: {msg}")

    items = body.get("d") or []
    item = items[0] if items else {}
    v = item.get("v") or {}
    if item.get("s") != "ok" or not isinstance(v, dict):
        raise FyersUnavailableError(f"Fyers has no quote for {fyers_symbol}")
    return FyersQuote(ltp=_price(v.get("lp")), bid=_price(v.get("bid")), ask=_price(v.get("ask")))
