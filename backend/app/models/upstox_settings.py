"""Upstox API credentials — the independent price source for Check Trades.

Singleton document; the service layer keeps at most one row.

Check Trades currently judges a fill against OUR OWN record of the market:
the tick we published at that second, and the minute candle we built from
those ticks. That answers "did we fill where we said we were quoting", which
is the question that matters most — but it cannot answer "were we quoting
the right price", because both sides of that comparison come from us.

Upstox is a second opinion from outside the platform. Operator: "Upstox ka
API set karunga, phir uske API price se match karunga ki price sahi mila ya
nahi."

The secret is encrypted at rest (AES-256-GCM, `app.utils.crypto`) — the API
KEY is not, because Upstox puts it in the authorize URL in the clear and it
identifies the app rather than authorising anything on its own. The access
token is likewise stored as given: it expires on its own each day, and a
token nobody can read is a token nobody can refresh from.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.core.config import settings as _cfg_settings
from app.models._base import TimestampMixin


class UpstoxSettings(TimestampMixin):
    # ── App credentials, from the Upstox developer console ────────────
    #: Public half. Travels in the authorize URL, so there is nothing to hide.
    api_key: str = ""
    #: Private half, ciphertext + its own IV, both base64.
    encrypted_api_secret: str = ""
    encrypted_api_secret_iv: str = ""

    #: Where Upstox sends the customer back. Must match the value registered
    #: in the Upstox app EXACTLY, which is why the UI shows it to be copied
    #: rather than asking the operator to type it. Derived from
    #: BACKEND_PUBLIC_URL: the exchange happens server-side, so it has to be
    #: a URL Upstox can reach, not a localhost left over from a dev box.
    redirect_url: str = Field(default_factory=lambda: _cfg_settings.upstox_redirect_url)

    # ── Session ──────────────────────────────────────────────────────
    access_token: str | None = None
    #: Upstox tokens expire daily rather than after a fixed TTL, so this is
    #: recorded from the response when given and otherwise left null.
    token_expiry: datetime | None = None
    is_connected: bool = False
    last_connected: datetime | None = None

    #: Why the last connect failed, for the status line in the admin UI. An
    #: OAuth failure is almost always a mismatched redirect URL or a secret
    #: pasted with whitespace, and neither is guessable from "failed".
    last_error: str | None = None

    #: Off by default. Having credentials saved is not the same as wanting
    #: every trade check to spend an API call on them.
    enabled: bool = False

    class Settings:
        name = "upstox_settings"
