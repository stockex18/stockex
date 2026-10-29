"""Leads from the `/start` landing page: send a code, save the lead, mark it
converted when the same mobile opens an account.

The form is public and every code is a paid SMS, so the send goes through the
same guards as signup: a valid 10-digit mobile, the per-number cooldown and
hourly cap, and the platform's daily cap (all in `sms_service`). A lead is
only saved with a code that was texted to that number, so a row in the list
is a reachable phone, not something a bot typed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from beanie import PydanticObjectId

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.lead import Lead, LeadStatus
from app.services import sms_service
from app.utils.otp import issue_otp, verify_otp
from app.utils.time_utils import now_utc
from app.utils.validators import is_valid_mobile_in, normalize_mobile_in

logger = logging.getLogger(__name__)

_OTP_PURPOSE = "lead"

#: Tracking tags are free text from a URL. Kept short and printable so a
#: crafted link cannot stuff the admin list.
_TAG_MAX = 80
_TAG_CLEAN = re.compile(r"[^\w\-. ]+")


def clean_mobile(mobile: str) -> str:
    m = normalize_mobile_in(mobile or "")
    if not is_valid_mobile_in(m):
        raise ValidationFailedError(
            "Enter a valid 10-digit mobile number", details={"field": "mobile"}
        )
    return m


def clean_tag(v: str | None) -> str | None:
    if not v:
        return None
    t = _TAG_CLEAN.sub("", str(v)).strip()[:_TAG_MAX]
    return t or None


def clean_text(v: str, *, field: str, min_len: int = 2, max_len: int = 80) -> str:
    t = " ".join(str(v or "").split())
    if len(t) < min_len:
        raise ValidationFailedError(f"Please enter your {field}", details={"field": field})
    return t[:max_len]


async def send_code(mobile: str) -> str:
    """Text a verification code. Returns the message to show the visitor."""
    m = clean_mobile(mobile)
    code = await issue_otp(_OTP_PURPOSE, m)
    try:
        await sms_service.send_otp(m, code)
    except sms_service.SmsThrottled as e:
        raise ValidationFailedError(str(e)) from e
    except sms_service.SmsError as e:
        raise ValidationFailedError(
            "We could not send the verification code right now. Please try again shortly."
        ) from e
    msg = f"Code sent to {sms_service.mask(m)}"
    if settings.APP_ENV == "development":
        msg += f" (dev only: {code})"
    return msg


async def submit(
    *,
    full_name: str,
    mobile: str,
    city: str,
    otp: str,
    tags: dict[str, Any],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Lead:
    """Save (or refresh) the lead for a verified mobile."""
    name = clean_text(full_name, field="name")
    town = clean_text(city, field="city")
    m = clean_mobile(mobile)
    if not otp or not await verify_otp(_OTP_PURPOSE, m, str(otp).strip()):
        raise ValidationFailedError(
            "That code is wrong or has expired. Please request a new one.",
            details={"field": "otp"},
        )

    now = now_utc()
    clean = {k: clean_tag(tags.get(k)) for k in (
        "ref_code", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    )}
    if clean["ref_code"]:
        clean["ref_code"] = clean["ref_code"].upper()

    lead = await Lead.find_one({"mobile": m})
    if lead is None:
        lead = Lead(
            full_name=name, mobile=m, city=town,
            last_submitted_at=now,
            ip_address=ip_address, user_agent=(user_agent or "")[:300] or None,
            **clean,
        )
        await _link_existing_account(lead)
        await lead.insert()
        logger.info("lead_created mobile=%s", sms_service.mask(m))
        return lead

    # The same person again: fresh details, and a new campaign tag only
    # replaces the old one when it is actually present -- the first link that
    # brought them in is not wiped by a later bare visit.
    lead.full_name = name
    lead.city = town
    lead.submissions = int(lead.submissions or 0) + 1
    lead.last_submitted_at = now
    for k, v in clean.items():
        if v:
            setattr(lead, k, v)
    if lead.status == LeadStatus.NOT_INTERESTED:
        lead.status = LeadStatus.NEW  # they came back; worth another call
    await _link_existing_account(lead)
    await lead.save()
    return lead


async def _link_existing_account(lead: Lead) -> None:
    """A visitor who already has an account is not a new prospect."""
    if lead.converted_user_id:
        return
    try:
        from app.models.user import User

        u = await User.find_one({"mobile": lead.mobile})
    except Exception:  # noqa: BLE001 -- a lookup failure must not lose the lead
        logger.warning("lead_account_lookup_failed", exc_info=True)
        return
    if u is not None:
        lead.converted_user_id = u.id
        lead.converted_at = lead.converted_at or now_utc()
        lead.status = LeadStatus.CONVERTED


async def mark_converted(mobile: str, user_id: PydanticObjectId) -> None:
    """Called at signup. Never raises -- a lead must not fail an account."""
    try:
        m = normalize_mobile_in(mobile or "")
        lead = await Lead.find_one({"mobile": m})
        if lead is None or lead.converted_user_id:
            return
        lead.status = LeadStatus.CONVERTED
        lead.converted_user_id = user_id
        lead.converted_at = now_utc()
        await lead.save()
    except Exception:  # noqa: BLE001
        logger.warning("lead_mark_converted_failed", exc_info=True)


# ── admin ───────────────────────────────────────────────────────────


def _query(status: str | None, q: str | None) -> dict[str, Any]:
    flt: dict[str, Any] = {}
    if status:
        try:
            flt["status"] = LeadStatus(status.upper()).value
        except ValueError as e:
            raise ValidationFailedError("Unknown lead status") from e
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        flt["$or"] = [
            {"full_name": rx}, {"mobile": rx}, {"city": rx},
            {"ref_code": rx}, {"utm_campaign": rx}, {"utm_source": rx},
        ]
    return flt


async def list_leads(
    *, status: str | None = None, q: str | None = None, page: int = 1, limit: int = 50
) -> tuple[list[Lead], int]:
    flt = _query(status, q)
    page = max(1, int(page))
    limit = min(max(1, int(limit)), 200)
    total = await Lead.find(flt).count()
    rows = (
        await Lead.find(flt).sort("-created_at").skip((page - 1) * limit).limit(limit).to_list()
    )
    return rows, total


async def all_leads(*, status: str | None = None, q: str | None = None) -> list[Lead]:
    return await Lead.find(_query(status, q)).sort("-created_at").limit(10_000).to_list()


async def counts() -> dict[str, int]:
    out = {s.value: 0 for s in LeadStatus}
    rows = await Lead.get_motor_collection().aggregate(
        [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ).to_list(length=None)
    for r in rows:
        if r.get("_id") in out:
            out[r["_id"]] = int(r["n"])
    return out


async def update_lead(lead_id: str, *, status: str | None, note: str | None) -> Lead:
    try:
        lead = await Lead.get(PydanticObjectId(lead_id))
    except Exception:  # noqa: BLE001 -- a malformed id is just "not found"
        lead = None
    if lead is None:
        raise NotFoundError("Lead not found")
    if status is not None:
        try:
            lead.status = LeadStatus(status.upper())
        except ValueError as e:
            raise ValidationFailedError("Unknown lead status") from e
    if note is not None:
        lead.note = str(note)[:1000]
    await lead.save()
    return lead


def to_out(lead: Lead) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "full_name": lead.full_name,
        "mobile": lead.mobile,
        "city": lead.city,
        "status": lead.status.value,
        "note": lead.note,
        "ref_code": lead.ref_code,
        "utm_source": lead.utm_source,
        "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign,
        "utm_content": lead.utm_content,
        "utm_term": lead.utm_term,
        "submissions": lead.submissions,
        "created_at": lead.created_at,
        "last_submitted_at": lead.last_submitted_at,
        "converted_user_id": str(lead.converted_user_id) if lead.converted_user_id else None,
        "converted_at": lead.converted_at,
    }
