"""Zerodha Kite Connect integration settings — single-row collection.

Stores admin-supplied API credentials, the day's access token (Kite tokens
expire at 08:00 IST every day), enabled segments, and the list of subscribed
instruments that the WebSocket ticker is following.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from beanie import Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.core.config import settings as _cfg_settings
from app.models._base import StrEnum, TimestampMixin


class WsStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class EnabledSegments(BaseModel):
    nseEq: bool = True
    bseEq: bool = True
    nseFut: bool = True
    nseOpt: bool = True
    mcxFut: bool = True
    mcxOpt: bool = True
    bseFut: bool = False
    bseOpt: bool = False


class SubscribedInstrument(BaseModel):
    """Mirrors the bharat schema 1:1 so existing UIs map cleanly."""

    token: int
    symbol: str
    exchange: str
    segment: str | None = None
    name: str | None = None
    lotSize: int = 1
    tickSize: float = 0.05
    expiry: str | None = None  # ISO date or null
    strike: float | None = None
    instrumentType: str | None = None  # EQ / FUT / CE / PE


class ZerodhaSettings(TimestampMixin):
    """One document per Zerodha API account (account_index 0 = primary, 1 = secondary)."""

    account_index: int = 0

    apiKey: str = ""
    apiSecret: str = ""
    accessToken: str | None = None
    refreshToken: str | None = None
    tokenExpiry: datetime | None = None
    isConnected: bool = False
    lastConnected: datetime | None = None

    enabledSegments: EnabledSegments = Field(default_factory=EnabledSegments)
    subscribedInstruments: list[SubscribedInstrument] = Field(default_factory=list)

    instrumentsLastFetched: datetime | None = None

    autoSyncEnabled: bool = True
    autoRemoveExpired: bool = True

    wsStatus: WsStatus = WsStatus.DISCONNECTED
    wsLastError: str | None = None

    # Derived from BACKEND_PUBLIC_URL, not hardcoded: a literal localhost
    # default meant every row created on a deployed box was born pointing at a
    # machine Kite cannot reach, and the connect then failed silently. Super
    # admin can still override it in the admin UI.
    redirectUrl: str = Field(default_factory=lambda: _cfg_settings.zerodha_redirect_url)

    class Settings:
        name = "zerodha_settings"
