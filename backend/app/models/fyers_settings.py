"""Fyers API credentials — the second price source for the order price check.

Singleton document; the service layer keeps at most one row.

Every MARKET order is filled on the Zerodha feed. Fyers is an outside second
opinion: the moment an order is placed we ask Fyers for the same contract's
price and compare. A mismatch is only REPORTED to the super admin — the order
is never blocked or delayed by this check. See `fyers_price_check`.

Same storage rules as `UpstoxSettings`: the secret is encrypted at rest
(AES-256-GCM, `app.utils.crypto`); the app id is not, because Fyers puts it in
the login URL in the clear. The access token expires by itself every day.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.core.config import settings as _cfg_settings
from app.models._base import TimestampMixin


class FyersSettings(TimestampMixin):
    # ── App credentials, from the Fyers API dashboard ─────────────────
    #: The "App ID" Fyers shows, e.g. "XB12345-100". Public half.
    app_id: str = ""
    #: Private half, ciphertext + its own IV, both base64.
    encrypted_secret: str = ""
    encrypted_secret_iv: str = ""

    #: Must match the redirect URL saved on the Fyers app EXACTLY, so the UI
    #: shows it to be copied rather than typed. Lives on the backend because
    #: the code-for-token exchange needs the secret.
    redirect_url: str = Field(default_factory=lambda: _cfg_settings.fyers_redirect_url)

    # ── Session ──────────────────────────────────────────────────────
    access_token: str | None = None
    is_connected: bool = False
    last_connected: datetime | None = None
    #: Why the last connect / quote failed, for the admin status line.
    last_error: str | None = None

    #: Off by default. Saved credentials are not the same as wanting every
    #: market order to spend a Fyers call.
    enabled: bool = False

    class Settings:
        name = "fyers_settings"
