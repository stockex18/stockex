"""Public lead capture for the `/start` landing page.

Two calls, both unauthenticated and both on the strict `auth` rate-limit
bucket because each code is a paid SMS:

    POST /api/v1/leads/otp   { mobile }                   -> texts a code
    POST /api/v1/leads       { full_name, mobile, city,
                               otp, website, ref_code,
                               utm_* }                     -> saves the lead

`website` is a honeypot: a hidden field real visitors never see. A request
that fills it gets the same "thank you" a person would, and nothing is saved.

Mounted at ``/api/v1`` from ``app/main.py``, next to the other public routes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.rate_limit import _client_ip, rate_limit
from app.schemas.common import APIResponse
from app.services import lead_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["public-leads"])

_THANKS = "Thank you! Our team will call you shortly."


class LeadOtpRequest(BaseModel):
    mobile: str = Field(max_length=20)


class LeadSubmit(BaseModel):
    full_name: str = Field(max_length=120)
    mobile: str = Field(max_length=20)
    city: str = Field(max_length=120)
    otp: str = Field(default="", max_length=8)
    #: Honeypot -- must stay empty.
    website: str = Field(default="", max_length=200)
    ref_code: str | None = Field(default=None, max_length=200)
    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=200)
    utm_term: str | None = Field(default=None, max_length=200)


@router.post("/otp", response_model=APIResponse[dict], dependencies=[rate_limit("auth")])
async def request_lead_otp(payload: LeadOtpRequest):
    msg = await lead_service.send_code(payload.mobile)
    return APIResponse(data={"sent": True}, message=msg)


@router.post("", response_model=APIResponse[dict], dependencies=[rate_limit("auth")])
async def submit_lead(payload: LeadSubmit, request: Request):
    if payload.website.strip():
        logger.info("lead_honeypot_tripped ip=%s", _client_ip(request))
        return APIResponse(data={"ok": True}, message=_THANKS)
    await lead_service.submit(
        full_name=payload.full_name,
        mobile=payload.mobile,
        city=payload.city,
        otp=payload.otp,
        tags=payload.model_dump(include={
            "ref_code", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
        }),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(data={"ok": True}, message=_THANKS)
