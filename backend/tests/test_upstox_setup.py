"""Upstox credentials for Check Trades — the setup, not the comparison yet.

Check Trades judges a fill against OUR record of the market: the tick we
published at that second, and the minute candle built from those ticks. That
answers "did we fill where we said we were quoting", which is the question
that matters most — but it cannot answer "were we quoting the right price",
because both sides of that comparison come from us.

Operator: "Upstox ka API set karunga, phir uske API price se match karunga
ki price sahi mila ya nahi. Yahi pe section de API aur secret daalne ke liye
aur redirect URL copy karne ke liye."

Three things have to line up and the third is the one that bites: the key,
the secret, and a redirect URL registered on the Upstox app byte-for-byte.
Upstox refuses the exchange on any mismatch and the error it returns does not
say which. So the URL is derived here and shown to be COPIED, never typed.

The endpoints below are v2 and come from Upstox's own documentation, not from
memory — a wrong OAuth URL costs the operator an afternoon.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import upstox as api
from app.core.config import settings
from app.main import app
from app.models.upstox_settings import UpstoxSettings
from app.services import upstox_service as svc


def _routes() -> list[str]:
    return [getattr(r, "path", "") for r in app.routes]


# ── the endpoints are the documented ones ─────────────────────────────
def test_the_oauth_urls_are_the_v2_ones():
    assert svc.AUTH_DIALOG == "https://api.upstox.com/v2/login/authorization/dialog"
    assert svc.TOKEN_URL == "https://api.upstox.com/v2/login/authorization/token"


def test_the_token_exchange_sends_every_field_upstox_requires():
    src = inspect.getsource(svc.exchange_code)
    for field in ("code", "client_id", "client_secret", "redirect_uri", "grant_type"):
        assert f'"{field}"' in src, field
    assert "authorization_code" in src


def test_the_exchange_sends_the_form_content_type():
    """Upstox wants x-www-form-urlencoded. Posting JSON is refused with an
    error that reads like a credential problem."""
    src = inspect.getsource(svc.exchange_code)
    assert "application/x-www-form-urlencoded" in src
    assert "data=form" in src


def test_candles_are_one_minute():
    """The tick store keeps two days; 1-minute candles are kept for six
    months, so the window Check Trades can ask about is always covered."""
    assert "1minute" in inspect.getsource(svc.minute_candles)


# ── the redirect URL ──────────────────────────────────────────────────
def test_the_redirect_url_points_at_the_backend():
    """The exchange needs the api_secret, which never leaves the server — so
    the callback cannot live on the admin front end."""
    assert settings.upstox_redirect_url.endswith("/api/v1/admin/upstox/callback")


def test_the_redirect_url_follows_the_public_backend_url():
    """A hardcoded localhost default is how a deployed box ends up pointing
    at a machine Upstox cannot reach, and the connect then fails silently."""
    src = inspect.getsource(type(settings).upstox_redirect_url.fget)
    assert "BACKEND_PUBLIC_URL" in src


def test_the_row_is_born_with_it_filled_in():
    assert "upstox_redirect_url" in inspect.getsource(UpstoxSettings)


# ── the secret is write-only ──────────────────────────────────────────
def test_the_secret_is_encrypted_at_rest():
    src = inspect.getsource(svc.save_credentials)
    assert "encrypt(" in src
    assert "encrypted_api_secret" in src


def test_the_status_payload_never_returns_the_secret():
    src = inspect.getsource(svc.status)
    assert "has_secret" in src
    assert "decrypt" not in src
    assert "api_secret" not in src.replace("encrypted_api_secret", "")


def test_an_empty_secret_does_not_wipe_the_saved_one():
    """The UI never sends the secret back, so a blanket write would erase it
    on every save of the key."""
    src = inspect.getsource(svc.save_credentials)
    assert "if api_secret:" in src


def test_whitespace_is_stripped_off_the_pasted_secret():
    """The commonest reason an exchange is refused, and Upstox's error says
    nothing about it."""
    src = inspect.getsource(svc.save_credentials)
    assert "api_secret.strip()" in src


def test_the_audit_entry_carries_no_credential():
    src = inspect.getsource(api.set_upstox_settings)
    assert 'k != "api_secret"' in src


# ── who may touch it ──────────────────────────────────────────────────
def test_every_settings_route_is_super_admin_only():
    """These are keys to an outside brokerage account."""
    for fn in (api.get_upstox_settings, api.set_upstox_settings,
               api.get_login_url, api.disconnect_upstox):
        assert "SuperAdmin" in inspect.getsource(fn), fn.__name__


def test_the_callback_is_public_and_says_why():
    """It is opened by a redirect from Upstox, which carries no session of
    ours. Safe because the code alone is worthless without the secret."""
    src = inspect.getsource(api.upstox_callback)
    assert "SuperAdmin" not in src
    assert "PUBLIC" in src


def test_the_routes_exist():
    for p in (
        "/api/v1/admin/upstox/settings",
        "/api/v1/admin/upstox/login-url",
        "/api/v1/admin/upstox/disconnect",
        "/api/v1/admin/upstox/callback",
    ):
        assert p in _routes(), p


# ── failing safe ──────────────────────────────────────────────────────
def test_a_disconnected_source_returns_no_candles_instead_of_raising():
    """A verification source that cannot answer should make the check say
    "no second opinion", not fail the whole report."""
    src = inspect.getsource(svc.minute_candles)
    assert "return []" in src
    assert "row.enabled and row.is_connected" in src


def test_a_dead_token_is_recorded_where_the_operator_can_see_it():
    src = inspect.getsource(svc.minute_candles)
    assert "last_error" in src and "is_connected = False" in src


def test_disconnect_keeps_the_credentials():
    """Reconnecting should be one click, not a retype of the secret."""
    src = inspect.getsource(svc.disconnect)
    assert "access_token = None" in src
    assert "encrypted_api_secret" not in src


def test_every_outbound_call_has_a_timeout():
    """Upstox is on the far side of the internet and none of this is on an
    order path."""
    assert "_TIMEOUT" in inspect.getsource(svc.exchange_code)
    assert "_TIMEOUT" in inspect.getsource(svc._get)


# ── the candle helper ─────────────────────────────────────────────────
def test_a_candle_is_matched_on_the_minute_prefix():
    """Upstox stamps the START of the minute and writes the +05:30 offset;
    matching the prefix sidesteps both."""
    rows = [
        ["2026-10-06T09:17:00+05:30", 1, 2, 3, 4, 5, 6],
        ["2026-10-06T09:16:00+05:30", 10, 20, 30, 40, 50, 60],
    ]
    assert svc.candle_at(rows, "2026-10-06T09:16")[1] == 10
    assert svc.candle_at(rows, "2026-10-06T09:18") is None
    assert svc.candle_at([], "2026-10-06T09:16") is None
