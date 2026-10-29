"""Leads from the public `/start` landing page.

A visitor who is not ready to open an account leaves a name, a verified mobile
and a city, and someone calls them back. One row per MOBILE: a second
submission from the same number updates the row and bumps `submissions`
rather than filing a duplicate the caller would ring twice.

Where the visitor came from is kept with the lead -- the broker referral code
(`?ref=`) and the ad campaign's UTM tags -- so the admin can see which links
and campaigns actually bring people in. Nothing here assigns the lead to a
broker; `ref_code` is recorded, not acted on.
"""

from __future__ import annotations

from datetime import datetime

from beanie import PydanticObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import StrEnum, TimestampMixin


class LeadStatus(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    #: Opened an account with the same mobile -- set automatically at signup.
    CONVERTED = "CONVERTED"
    NOT_INTERESTED = "NOT_INTERESTED"


class Lead(TimestampMixin):
    full_name: str
    #: 10-digit Indian mobile, normalised (no +91), verified by SMS OTP.
    mobile: str
    city: str

    status: LeadStatus = LeadStatus.NEW
    #: The admin's own note from the call.
    note: str = ""

    # ── where they came from ────────────────────────────────────────
    ref_code: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None

    #: How many times this mobile has submitted the form.
    submissions: int = 1
    last_submitted_at: datetime | None = None

    ip_address: str | None = None
    user_agent: str | None = None

    #: The account opened with this mobile, once there is one.
    converted_user_id: PydanticObjectId | None = None
    converted_at: datetime | None = None

    class Settings:
        name = "leads"
        indexes = [
            IndexModel([("mobile", ASCENDING)], unique=True),
            # The admin list: newest first, optionally narrowed by status.
            IndexModel([("status", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
