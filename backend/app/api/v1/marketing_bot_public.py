"""Public mobile-OTP check for StockEx Buddy, the home-page help chat.

Visitors verify a mobile number before the chat answers. Two calls, both
unauthenticated and both on the strict `auth` rate-limit bucket because each
code is a paid SMS:

    POST /api/v1/marketing-bot/otp     { mobile }        -> texts a code
    POST /api/v1/marketing-bot/verify  { mobile, otp }   -> checks it
    POST /api/v1/marketing-bot/lead    { mobile, chat_token,
                                         full_name, ... } -> saves the lead

They reuse the shared OTP store (app/utils/otp.py, purpose "marketing_bot")
and SMS sender (app/services/sms_service.py), so the same cooldown, per-number
hourly limit and site-wide daily cap apply as for signup and lead codes.

The caller is the frontend's Next.js server (frontend-user/app/api/
faq-bot/otp + /verify), which forwards the visitor's IP in
X-Forwarded-For and, on success, sets its own signed session cookie. This
API keeps no session: it only says whether the code was right, plus a
one-time `chat_token` (lead_service.issue_chat_token) and whether that mobile
is already a lead. The chat then shows the same form as the /start page and
files it with the token -- one SMS for both chat and lead.

Mounted at ``/api/v1`` from ``app/main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import ValidationFailedError
from app.core.rate_limit import _client_ip, rate_limit
from app.schemas.common import APIResponse
from app.services import lead_service, sms_service
from app.services.lead_service import clean_mobile
from app.utils.otp import issue_otp, verify_otp

router = APIRouter(prefix="/marketing-bot", tags=["public-marketing-bot"])

_OTP_PURPOSE = "marketing_bot"


class BotOtpRequest(BaseModel):
    mobile: str = Field(max_length=20)


class BotOtpVerify(BaseModel):
    mobile: str = Field(max_length=20)
    otp: str = Field(max_length=8)


class BotLeadSubmit(BaseModel):
    mobile: str = Field(max_length=20)
    chat_token: str = Field(max_length=100)
    full_name: str = Field(max_length=120)
    city: str = Field(max_length=120)
    email: str = Field(default="", max_length=254)
    experience: str = Field(default="", max_length=20)
    enquiry_for: str = Field(default="", max_length=20)
    question: str = Field(default="", max_length=2000)


@router.post("/otp", response_model=APIResponse[dict], dependencies=[rate_limit("auth")])
async def send_bot_otp(payload: BotOtpRequest):
    m = clean_mobile(payload.mobile)
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
    return APIResponse(data={"sent": True}, message=msg)


@router.post("/verify", response_model=APIResponse[dict], dependencies=[rate_limit("auth")])
async def verify_bot_otp(payload: BotOtpVerify):
    m = clean_mobile(payload.mobile)
    if not await verify_otp(_OTP_PURPOSE, m, payload.otp.strip()):
        raise ValidationFailedError(
            "That code is wrong or has expired. Please request a new one.",
            details={"field": "otp"},
        )
    return APIResponse(
        data={
            "verified": True,
            "mobile": m,
            "chat_token": await lead_service.issue_chat_token(m),
            "has_lead": await lead_service.has_lead(m),
        },
        message="Verified",
    )


@router.post("/lead", response_model=APIResponse[dict], dependencies=[rate_limit("auth")])
async def submit_bot_lead(payload: BotLeadSubmit, request: Request):
    await lead_service.submit_from_chat(
        full_name=payload.full_name,
        mobile=payload.mobile,
        city=payload.city,
        email=payload.email,
        experience=payload.experience,
        enquiry_for=payload.enquiry_for,
        question=payload.question,
        chat_token=payload.chat_token,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return APIResponse(data={"ok": True}, message="Thank you! Our team will call you shortly.")
