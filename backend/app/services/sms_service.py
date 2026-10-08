"""OTP delivery over SMS — AquaSMS on a registered DLT template.

Three things here are easy to get wrong and expensive to get wrong, so they are
spelled out rather than left to be rediscovered.

THE TEXT MUST MATCH THE TEMPLATE. An Indian OTP goes out on a DLT-registered
template, and the carrier drops, silently, any message whose text does not match
it — the API still says success and nothing is delivered. The registered body is
"Your OTP code for verification is : {#var#} CRTFUL"; the code replaces
`{#var#}` and nothing else about the sentence may change. The template, its id,
the entity id and the sender all live in settings together because they only
work together.

HTTP 200 DOES NOT MEAN IT WORKED. Checked against the live account: a wrong key
comes back as HTTP 200 with `[{"responseCode":"INVALID_KEY"}]`. A sender that
trusts the status code reports every failure as a delivered code, so the reply
body is read and logged.

EVERY TEXT IS A PAID CREDIT, AND THE ENDPOINT IS PUBLIC. The account this was
built against had 16 credits. So sending is bounded three ways before a
request ever leaves the building: a cooldown per number, an hourly cap per
number, and a platform-wide daily cap. A script hammering "send code" burns the
daily cap and stops; it cannot drain the account.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


class _DropSmsRequestLines(logging.Filter):
    """Keep the SMS request URL out of the logs.

    AquaSMS takes everything as a GET query string, and httpx logs every request
    it makes — at INFO, URL and all — through its own logger. That line carries
    the account's API key AND the one-time code itself (`message=...+123456+...`),
    so left alone every OTP sent would write a working credential and a working
    login code into the journal. Found by a test that checked the log, not by
    reading the code.

    Only records naming the send endpoint are dropped; httpx's logging for every
    other caller is untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return "/sendSMS" not in record.getMessage()
        except Exception:  # noqa: BLE001 — a log filter must never raise
            return True


logging.getLogger("httpx").addFilter(_DropSmsRequestLines())

#: Words that mean the gateway refused, in a reply whose HTTP status was 200.
#: Matched on the lower-cased `responseCode` (or the raw text when the reply is
#: not JSON). Deliberately broad: the cost of calling a real failure a success
#: is a user waiting for a code that never comes.
_FAILURE_WORDS = (
    "invalid", "insufficient", "low_balance", "fail", "error", "denied",
    "blocked", "expired", "not allowed", "not_allowed", "wrong", "reject",
    "unauthor", "no credit",
)


class SmsError(Exception):
    """The gateway refused, or could not be reached."""


class SmsThrottled(Exception):
    """Too many texts — to this number, or from the platform today."""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


def national_number(mobile: str) -> str:
    """The 10-digit number the gateway wants, whatever shape came in."""
    digits = "".join(c for c in str(mobile or "") if c.isdigit())
    return digits[-10:]


def mask(mobile: str) -> str:
    n = national_number(mobile)
    return "******" + n[-4:] if len(n) >= 4 else "****"


def render_otp_message(code: str) -> str:
    """The registered DLT text with the code in place of `{#var#}`."""
    return settings.AQUASMS_OTP_TEMPLATE.replace("{#var#}", str(code))


def is_configured() -> bool:
    if settings.SMS_PROVIDER == "aquasms":
        return bool(
            settings.AQUASMS_USERNAME
            and settings.SMS_API_KEY.get_secret_value()
            and settings.AQUASMS_PEID
            and settings.AQUASMS_OTP_TEMPLATE_ID
            and settings.SMS_SENDER_ID
        )
    return settings.SMS_PROVIDER == "mock"


def reply_is_failure(body: str) -> bool:
    """Did the gateway's reply say no? (Its status code never does.)"""
    import json

    text = (body or "").strip()
    probe = text
    try:
        parsed = json.loads(text)
        first = parsed[0] if isinstance(parsed, list) and parsed else parsed
        if isinstance(first, dict):
            probe = str(first.get("responseCode") or first.get("status") or first.get("message") or "")
    except Exception:  # noqa: BLE001 — a plain-text reply is still a reply
        pass
    probe = probe.lower()
    return any(w in probe for w in _FAILURE_WORDS)


async def _throttle(mobile: str) -> None:
    """Raise SmsThrottled unless this text is allowed. Free: no request is made."""
    n = national_number(mobile)
    r = get_redis()

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    day_key = f"sms:day:{day}"
    sent_today = int(await r.get(day_key) or 0)
    if sent_today >= settings.SMS_OTP_DAILY_CAP:
        logger.error("sms_daily_cap_reached cap=%s", settings.SMS_OTP_DAILY_CAP)
        raise SmsThrottled("Verification texts are paused for today. Please try again tomorrow.")

    cool_key = f"sms:cool:{n}"
    # NX: only the first caller inside the window gets through.
    if not await r.set(cool_key, "1", nx=True, ex=settings.SMS_OTP_COOLDOWN_SEC):
        ttl = int(await r.ttl(cool_key) or settings.SMS_OTP_COOLDOWN_SEC)
        raise SmsThrottled(f"Please wait {max(ttl, 1)} seconds before asking for another code.", max(ttl, 1))

    hour_key = f"sms:hour:{n}"
    count = int(await r.incr(hour_key))
    if count == 1:
        await r.expire(hour_key, 3600)
    if count > settings.SMS_OTP_PER_NUMBER_HOURLY:
        raise SmsThrottled("Too many codes requested for this number. Please try again in an hour.", 3600)

    pipe = r.pipeline()
    pipe.incr(day_key)
    pipe.expire(day_key, 90_000)
    await pipe.execute()


async def send_otp(mobile: str, code: str) -> None:
    """Text `code` to `mobile`. Raises SmsThrottled or SmsError; returns on success."""
    n = national_number(mobile)
    if len(n) != 10:
        raise SmsError("Not a 10-digit mobile number")

    await _throttle(n)
    message = render_otp_message(code)

    if settings.SMS_PROVIDER == "mock":
        # Development only: nothing leaves the machine, and the code is in the log
        # because there is no phone to read it from.
        logger.warning("sms_mock_otp mobile=%s code=%s", mask(n), code)
        return
    if settings.SMS_PROVIDER != "aquasms":
        raise SmsError(f"SMS provider '{settings.SMS_PROVIDER}' has no OTP sender")
    if not is_configured():
        raise SmsError("AquaSMS is not fully configured")

    params = {
        "username": settings.AQUASMS_USERNAME,
        "apikey": settings.SMS_API_KEY.get_secret_value(),
        "message": message,
        "sendername": settings.SMS_SENDER_ID,
        "smstype": "TRANS",
        "numbers": n,
        "peid": settings.AQUASMS_PEID,
        "templateid": settings.AQUASMS_OTP_TEMPLATE_ID,
    }
    url = settings.AQUASMS_BASE_URL.rstrip("/") + "/v2/sendSMS"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.get(url, params=params)
    except Exception as e:  # noqa: BLE001
        logger.error("sms_unreachable mobile=%s err=%s", mask(n), type(e).__name__)
        raise SmsError("Could not reach the SMS gateway") from e

    body = (resp.text or "")[:300]
    if resp.status_code != 200 or reply_is_failure(body):
        # Never log the request URL: it carries the api key.
        logger.error("sms_refused mobile=%s http=%s reply=%s", mask(n), resp.status_code, body)
        raise SmsError("The SMS gateway did not accept the message")
    # The reply is logged on success too. The first live send is how the shape of
    # a good reply gets learned, and "it said ok" is not worth much without it.
    logger.info("sms_otp_sent mobile=%s reply=%s", mask(n), body)
