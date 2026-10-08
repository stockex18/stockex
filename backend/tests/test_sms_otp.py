"""OTP over SMS: forgot-password and signup.

Before this, "forgot password" could not complete for anyone. `/forgot-password`
made a code, stored it, and sent it to nobody — the code carried a TODO where
the delivery was meant to go — and signup had no code at all.

Facts about the gateway that these tests are built around, all observed on the
live account rather than assumed:

  * a wrong key comes back as HTTP 200 with `[{"responseCode":"INVALID_KEY"}]`,
    so the status code says nothing and the BODY has to be read
  * the account had 16 credits, and every text is one of them
  * the carrier silently drops a message whose text differs from the registered
    DLT template, so the text is part of the contract
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.api.v1.user import auth as api
from app.core.config import settings
from app.core.exceptions import ConflictError, InvalidCredentialsError, ValidationFailedError
from app.schemas.auth import ForgotPasswordRequest, OtpRequest
from app.services import sms_service as sms

KEY = "k-test-key-0000"


# ── a stand-in for Redis, just enough of it ──────────────────────────
class FakeRedis:
    def __init__(self):
        self.d: dict[str, int | str] = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.d:
            return None
        self.d[k] = v
        return True

    async def ttl(self, k):
        return 42 if k in self.d else -2

    async def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1
        return self.d[k]

    async def expire(self, k, s):
        return True

    def pipeline(self):
        r = self

        class P:
            def __init__(self):
                self.ops = []

            def incr(self, k):
                self.ops.append(("incr", k))
                return self

            def expire(self, k, s):
                return self

            async def execute(self):
                for op, k in self.ops:
                    if op == "incr":
                        await r.incr(k)

        return P()


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(sms, "get_redis", lambda: r)
    return r


@pytest.fixture
def aqua(monkeypatch):
    """AquaSMS fully configured, and a recorder in place of the network."""
    for k, v in {
        "SMS_PROVIDER": "aquasms",
        "AQUASMS_USERNAME": "9876543296",
        "AQUASMS_PEID": "1201000000000000001",
        "AQUASMS_OTP_TEMPLATE_ID": "1207000000000000001",
        "SMS_SENDER_ID": "CRTFUL",
        "SMS_OTP_COOLDOWN_SEC": 60,
        "SMS_OTP_PER_NUMBER_HOURLY": 5,
        "SMS_OTP_DAILY_CAP": 300,
    }.items():
        monkeypatch.setattr(settings, k, v)
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "SMS_API_KEY", SecretStr(KEY))

    seen: list[httpx.Request] = []
    reply = {"status": 200, "text": '[{"responseCode":"Message Submitted Successfully"}]'}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(reply["status"], text=reply["text"])

    real = httpx.AsyncClient
    monkeypatch.setattr(
        sms.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    return seen, reply


def run(coro):
    return asyncio.run(coro)


# ── the text is the DLT template, with the code in it ────────────────
def test_the_message_is_the_registered_template_with_only_the_code_filled_in():
    """Anything else and the carrier drops it while the API says success."""
    assert sms.render_otp_message("123456") == "Your OTP code for verification is : 123456 CRTFUL"


def test_the_template_is_not_reflowed_or_trimmed():
    assert "{#var#}" in settings.AQUASMS_OTP_TEMPLATE
    assert settings.AQUASMS_OTP_TEMPLATE.count("{#var#}") == 1


# ── numbers ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", ["9876543296", "+919876543296", "91 98765 43296", "98765-43296"])
def test_any_indian_format_becomes_the_ten_digits_the_gateway_wants(raw):
    assert sms.national_number(raw) == "9876543296"


def test_a_number_is_masked_in_logs():
    assert sms.mask("9876543296") == "******3296"
    assert "9876" not in sms.mask("9876543296")


# ── reading the reply, not the status ────────────────────────────────
def test_the_wrong_key_reply_is_a_failure_even_though_http_said_200():
    """Exactly what the live account returned for a bad key."""
    assert sms.reply_is_failure('[{"responseCode":"INVALID_KEY"}]') is True


@pytest.mark.parametrize("body", [
    '[{"responseCode":"INSUFFICIENT_BALANCE"}]',
    '[{"responseCode":"INVALID_TEMPLATE"}]',
    '[{"responseCode":"Sender not allowed"}]',
    "Invalid username",
    "error",
])
def test_other_refusals_are_failures_too(body):
    assert sms.reply_is_failure(body) is True


@pytest.mark.parametrize("body", [
    '[{"responseCode":"Message Submitted Successfully","msgid":"abc"}]',
    "Message Submitted Successfully",
    "",
])
def test_a_normal_acceptance_is_not(body):
    assert sms.reply_is_failure(body) is False


# ── what goes on the wire ────────────────────────────────────────────
def test_the_request_carries_every_field_dlt_requires(aqua, redis):
    seen, _ = aqua
    run(sms.send_otp("9876543296", "654321"))
    assert len(seen) == 1
    req = seen[0]
    q = dict(req.url.params)
    assert req.url.scheme == "https"
    assert req.url.path == "/v2/sendSMS"
    assert q["smstype"] == "TRANS"
    assert q["sendername"] == "CRTFUL"
    assert q["numbers"] == "9876543296"
    assert q["peid"] == "1201000000000000001"
    assert q["templateid"] == "1207000000000000001"
    assert q["message"] == "Your OTP code for verification is : 654321 CRTFUL"
    assert q["apikey"] == KEY


def test_a_refused_message_raises_and_the_key_never_reaches_the_log(aqua, redis, caplog):
    seen, reply = aqua
    reply["text"] = '[{"responseCode":"INVALID_KEY"}]'
    with caplog.at_level(logging.INFO):
        with pytest.raises(sms.SmsError):
            run(sms.send_otp("9876543296", "111111"))
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "sms_refused" in logged
    assert KEY not in logged
    assert "apikey" not in logged.lower()


def test_a_non_200_is_a_failure(aqua, redis):
    seen, reply = aqua
    reply["status"] = 500
    with pytest.raises(sms.SmsError):
        run(sms.send_otp("9876543296", "111111"))


def test_a_number_that_is_not_ten_digits_is_refused_before_anything_is_spent(aqua, redis):
    seen, _ = aqua
    with pytest.raises(sms.SmsError):
        run(sms.send_otp("12345", "111111"))
    assert seen == []


def test_an_unconfigured_gateway_refuses_rather_than_sending_blind(aqua, redis, monkeypatch):
    seen, _ = aqua
    monkeypatch.setattr(settings, "AQUASMS_PEID", "")
    assert sms.is_configured() is False
    with pytest.raises(sms.SmsError):
        run(sms.send_otp("9876543296", "111111"))
    assert seen == []


def test_the_mock_provider_sends_nothing(aqua, redis, monkeypatch):
    seen, _ = aqua
    monkeypatch.setattr(settings, "SMS_PROVIDER", "mock")
    run(sms.send_otp("9876543296", "111111"))
    assert seen == []


# ── spending: every text is a credit ─────────────────────────────────
def test_a_second_code_inside_the_cooldown_is_refused_and_costs_nothing(aqua, redis):
    seen, _ = aqua
    run(sms.send_otp("9876543296", "111111"))
    with pytest.raises(sms.SmsThrottled) as e:
        run(sms.send_otp("9876543296", "222222"))
    assert e.value.retry_after > 0
    assert len(seen) == 1


def test_one_numbers_cooldown_does_not_block_another(aqua, redis):
    seen, _ = aqua
    run(sms.send_otp("9876543296", "111111"))
    run(sms.send_otp("9876543297", "222222"))
    assert len(seen) == 2


def test_a_number_is_capped_per_hour(aqua, redis, monkeypatch):
    seen, _ = aqua
    monkeypatch.setattr(settings, "SMS_OTP_PER_NUMBER_HOURLY", 2)
    for _ in range(2):
        redis.d.pop("sms:cool:9876543296", None)  # the cooldown has passed
        run(sms.send_otp("9876543296", "111111"))
    redis.d.pop("sms:cool:9876543296", None)
    with pytest.raises(sms.SmsThrottled):
        run(sms.send_otp("9876543296", "111111"))
    assert len(seen) == 2


def test_the_platform_has_a_daily_ceiling_whoever_is_asking(aqua, redis, monkeypatch):
    """The endpoint is public. This is the most a script can cost."""
    seen, _ = aqua
    monkeypatch.setattr(settings, "SMS_OTP_DAILY_CAP", 2)
    run(sms.send_otp("9876543291", "111111"))
    run(sms.send_otp("9876543292", "111111"))
    with pytest.raises(sms.SmsThrottled):
        run(sms.send_otp("9876543293", "111111"))
    assert len(seen) == 2


# ── /otp/request ─────────────────────────────────────────────────────
@pytest.fixture
def spies(monkeypatch):
    calls = {"issue": [], "send": [], "verify": []}

    async def issue(purpose, ident, **kw):
        calls["issue"].append((purpose, ident))
        return "246810"

    async def send(mobile, code):
        calls["send"].append((mobile, code))

    async def verify(purpose, ident, code):
        calls["verify"].append((purpose, ident, code))
        return code == "246810"

    monkeypatch.setattr(api, "issue_otp", issue)
    monkeypatch.setattr(api, "verify_otp", verify)
    monkeypatch.setattr(sms, "send_otp", send)
    return calls


def _free_mobile(monkeypatch, taken=None):
    async def f(email, mobile, role=None):
        return taken

    monkeypatch.setattr(api.user_service, "email_or_mobile_taken", f)


def test_signup_otp_goes_to_the_mobile_that_was_typed(spies, monkeypatch):
    _free_mobile(monkeypatch)
    run(api.request_otp(OtpRequest(identifier="+91 98765 43296", purpose="register")))
    assert spies["issue"] == [("register", "9876543296")]
    assert spies["send"] == [("9876543296", "246810")]


def test_a_malformed_mobile_is_refused_before_a_code_is_made(spies, monkeypatch):
    _free_mobile(monkeypatch)
    with pytest.raises(ValidationFailedError):
        run(api.request_otp(OtpRequest(identifier="12345", purpose="register")))
    assert spies["issue"] == [] and spies["send"] == []


def test_an_already_registered_mobile_is_not_texted(spies, monkeypatch):
    """Spending a credit to send a code to someone who is already a customer."""
    _free_mobile(monkeypatch, taken="mobile")
    with pytest.raises(ConflictError):
        run(api.request_otp(OtpRequest(identifier="9876543296", purpose="register")))
    assert spies["send"] == []


def test_a_throttled_signup_asks_the_user_to_wait(spies, monkeypatch):
    _free_mobile(monkeypatch)

    async def throttled(mobile, code):
        raise sms.SmsThrottled("Please wait 30 seconds before asking for another code.", 30)

    monkeypatch.setattr(sms, "send_otp", throttled)
    with pytest.raises(ValidationFailedError, match="wait 30"):
        run(api.request_otp(OtpRequest(identifier="9876543296", purpose="register")))


def test_a_gateway_failure_on_signup_is_said_not_hidden_and_leaks_no_detail(spies, monkeypatch):
    """There is no account to protect on a signup, and "a code is on its way"
    for one that is not is the worst possible answer."""
    _free_mobile(monkeypatch)

    async def down(mobile, code):
        raise sms.SmsError("INVALID_KEY sk-secret")

    monkeypatch.setattr(sms, "send_otp", down)
    with pytest.raises(ValidationFailedError) as e:
        run(api.request_otp(OtpRequest(identifier="9876543296", purpose="register")))
    assert "could not send" in str(e.value).lower()
    assert "INVALID_KEY" not in str(e.value) and "sk-secret" not in str(e.value)


@pytest.mark.parametrize("purpose", ["login", "withdrawal"])
def test_purposes_nobody_delivers_never_cost_a_text(spies, purpose):
    run(api.request_otp(OtpRequest(identifier="9876543296", purpose=purpose)))
    assert spies["send"] == []


def test_reset_through_the_generic_endpoint_takes_the_forgot_password_path(spies, monkeypatch):
    async def find(identifier, roles=None):
        return type("U", (), {"email": "a@b.c", "mobile": "9876543296", "id": "u1"})()

    monkeypatch.setattr(api.user_service, "find_by_identifier", find)
    run(api.request_otp(OtpRequest(identifier="9876543296", purpose="reset_password")))
    assert spies["send"] == [("9876543296", "246810")]


# ── forgot password ──────────────────────────────────────────────────
def _user(monkeypatch, user):
    async def find(identifier, roles=None):
        return user

    monkeypatch.setattr(api.user_service, "find_by_identifier", find)


class _U:
    email = "a@b.c"
    mobile = "9876543296"
    id = "u1"


def test_forgot_password_now_actually_sends_the_code(spies, monkeypatch):
    _user(monkeypatch, _U())
    run(api.forgot_password(ForgotPasswordRequest(identifier="9876543296")))
    assert spies["issue"] == [("reset_password", "a@b.c")]
    assert spies["send"] == [("9876543296", "246810")]


def test_the_code_goes_to_the_number_on_file_not_one_the_caller_chose(spies, monkeypatch):
    """Otherwise this is a free "text anyone a code" button."""
    _user(monkeypatch, _U())
    run(api.forgot_password(ForgotPasswordRequest(identifier="user@example.com")))
    assert spies["send"][0][0] == "9876543296"


def test_an_unknown_account_gets_no_text_and_the_same_answer(spies, monkeypatch):
    _user(monkeypatch, None)
    unknown = run(api.forgot_password(ForgotPasswordRequest(identifier="nobody@x.io")))
    assert spies["send"] == [] and spies["issue"] == []
    _user(monkeypatch, _U())
    known = run(api.forgot_password(ForgotPasswordRequest(identifier="9876543296")))
    assert unknown.data.message == known.data.message


@pytest.mark.parametrize("exc", [sms.SmsThrottled("slow down", 30), sms.SmsError("down")])
def test_a_failure_for_a_real_account_looks_like_a_success_to_the_caller(spies, monkeypatch, exc):
    """If throttling or a gateway error only ever happened for REAL accounts,
    it would be a way to find out which numbers are registered."""
    _user(monkeypatch, _U())

    async def boom(mobile, code):
        raise exc

    monkeypatch.setattr(sms, "send_otp", boom)
    out = run(api.forgot_password(ForgotPasswordRequest(identifier="9876543296")))
    assert out.data.message == "If an account exists, a reset code has been sent"


# ── signup gate ──────────────────────────────────────────────────────
class _Reg:
    email = "new@example.com"
    mobile = "9876543296"
    otp: str | None = None


def _gate(monkeypatch, *, on=True, configured=True, conflict=None):
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", on)
    monkeypatch.setattr(sms, "is_configured", lambda: configured)

    async def taken(email, mobile, role=None):
        return conflict

    monkeypatch.setattr(api.user_service, "email_or_mobile_taken", taken)


def _payload(otp=None):
    p = _Reg()
    p.otp = otp
    return p


def test_with_the_gate_off_signup_is_exactly_as_it_was(spies, monkeypatch):
    _gate(monkeypatch, on=False)
    run(api._require_register_otp(_payload()))
    assert spies["verify"] == []


def test_the_gate_fails_closed_when_the_gateway_is_not_configured(spies, monkeypatch):
    """An OTP check that opens when its provider is misconfigured is not a check."""
    _gate(monkeypatch, configured=False)
    with pytest.raises(ValidationFailedError, match="unavailable"):
        run(api._require_register_otp(_payload("246810")))
    assert spies["verify"] == []


def test_a_signup_without_a_code_is_refused(spies, monkeypatch):
    _gate(monkeypatch)
    with pytest.raises(ValidationFailedError, match="verification code"):
        run(api._require_register_otp(_payload(None)))


def test_a_wrong_code_is_refused(spies, monkeypatch):
    _gate(monkeypatch)
    with pytest.raises(InvalidCredentialsError):
        run(api._require_register_otp(_payload("000000")))


def test_the_right_code_passes_and_is_checked_against_the_mobile(spies, monkeypatch):
    _gate(monkeypatch)
    run(api._require_register_otp(_payload("246810")))
    assert spies["verify"] == [("register", "9876543296", "246810")]


def test_a_taken_email_is_reported_before_the_code_is_spent(spies, monkeypatch):
    """A code is single-use and costs a text. Burning it on a signup that was
    always going to be refused would charge the user twice."""
    _gate(monkeypatch, conflict="email")
    with pytest.raises(ConflictError):
        run(api._require_register_otp(_payload("246810")))
    assert spies["verify"] == []


def test_the_gate_runs_before_any_account_is_created():
    import inspect

    src = inspect.getsource(api.demo_register)
    assert src.index("_require_register_otp") < src.index("_create_signup_user")


def test_the_signup_schema_carries_the_code():
    from app.schemas.auth import RegisterRequest

    assert "otp" in RegisterRequest.model_fields
    assert RegisterRequest.model_fields["otp"].default is None


def test_the_signup_gate_defaults_off_so_the_backend_can_ship_before_the_app():
    assert type(settings).model_fields["SMS_OTP_ON_REGISTER"].default is False


def test_a_successful_send_leaves_neither_the_key_nor_the_code_in_the_log(aqua, redis, caplog):
    """The code and the key are both in the request URL, and httpx logs request
    URLs at INFO. A log that holds every live OTP is a login for anyone who can
    read it."""
    with caplog.at_level(logging.DEBUG):
        run(sms.send_otp("9876543296", "908172"))
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "sms_otp_sent" in logged
    assert KEY not in logged
    assert "908172" not in logged
    assert "9876543296" not in logged  # only the masked form


# ── the signup form and forgot-password page ─────────────────────────
import pathlib as _pl

_FE = _pl.Path(__file__).resolve().parents[2] / "frontend-user"


def _fe(*parts):
    return _FE.joinpath(*parts).read_text(encoding="utf-8", errors="ignore")


def test_signup_config_says_a_code_is_wanted_only_when_it_will_really_be_sent(monkeypatch):
    """On with no working gateway would show a box that can never be filled."""
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", True)
    monkeypatch.setattr(sms, "is_configured", lambda: False)
    assert run(api.signup_config()).data == {"sms_otp": False}
    monkeypatch.setattr(sms, "is_configured", lambda: True)
    assert run(api.signup_config()).data == {"sms_otp": True}
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", False)
    assert run(api.signup_config()).data == {"sms_otp": False}


def test_the_form_asks_the_server_instead_of_assuming():
    s = _fe("app", "(auth)", "register", "page.tsx")
    assert "AuthAPI.signupConfig()" in s
    assert "const needOtp = !!signupCfg?.sms_otp" in s
    # The whole block hangs off it, so with the check off nothing renders.
    assert "{needOtp && (" in s


def test_the_code_box_only_appears_for_the_number_the_code_was_sent_to():
    s = _fe("app", "(auth)", "register", "page.tsx")
    assert "const codeIsForThisNumber = otpSentTo !== null && otpSentTo === mobileVal" in s
    assert "{codeIsForThisNumber ? (" in s


def test_changing_the_number_throws_the_old_code_away():
    s = _fe("app", "(auth)", "register", "page.tsx")
    assert 'form.setValue("otp", "")' in s


def test_signup_is_blocked_client_side_until_a_code_was_sent_and_is_six_digits():
    s = _fe("app", "(auth)", "register", "page.tsx")
    assert "Send a verification code to this mobile first" in s
    assert "Enter the 4-digit code from the SMS" in s


def test_the_code_is_sent_with_the_signup_only_when_it_is_asked_for():
    s = _fe("app", "(auth)", "register", "page.tsx")
    assert "otp: needOtp ? values.otp : undefined" in s


def test_resend_is_throttled_in_the_ui_too():
    """The server enforces it; the button just does not invite the click."""
    s = _fe("app", "(auth)", "register", "page.tsx")
    assert "setCooldown(60)" in s
    assert "cooldown > 0" in s


def test_the_client_can_ask_for_a_code_and_send_one_back():
    s = _fe("lib", "api.ts")
    assert "requestSignupOtp" in s and 'purpose: "register"' in s
    assert s.count("otp?: string;") >= 2  # register and demoRegister


def test_forgot_password_says_the_code_arrives_by_sms():
    s = _fe("app", "(auth)", "forgot-password", "page.tsx")
    assert "text a reset code" in s
    assert "texted to your registered mobile" in s


# ── four digits ──────────────────────────────────────────────────────
def test_a_code_is_four_digits_and_only_digits():
    from app.utils.otp import OTP_LENGTH, generate_otp

    assert OTP_LENGTH == 4
    for _ in range(300):
        c = generate_otp()
        assert len(c) == 4 and c.isdigit()


def test_leading_zeros_survive_because_the_code_is_text_not_a_number():
    """0042 must stay 0042 all the way to the SMS, or 1 in 10 codes is wrong."""
    from app.utils.otp import generate_otp

    seen = {generate_otp() for _ in range(3000)}
    assert any(c.startswith("0") for c in seen)
    assert all(len(c) == 4 for c in seen)


def test_the_four_digit_code_fits_the_registered_dlt_text():
    assert sms.render_otp_message("0427") == "Your OTP code for verification is : 0427 CRTFUL"


def test_the_screens_ask_for_four_digits_not_six():
    reg = _fe("app", "(auth)", "register", "page.tsx")
    assert "maxLength={4}" in reg and "4-digit code" in reg
    assert r"/^\d{4}$/" in reg
    forgot = _fe("app", "(auth)", "forgot-password", "page.tsx")
    assert "maxLength={4}" in forgot and "Enter 4-digit code" in forgot


def test_the_authenticator_app_codes_stay_six_digits():
    """Different thing entirely (TOTP, set by the standard). Shortening the SMS
    code must not reach into 2FA."""
    assert "maxLength={6}" in _fe("app", "(auth)", "2fa", "page.tsx")
    assert "maxLength={6}" in _fe("app", "(auth)", "login", "page.tsx")


def test_the_new_password_can_be_shown_while_typing():
    """Typed blind on a phone, a reset ends in a second reset."""
    s = _fe("app", "(auth)", "forgot-password", "page.tsx")
    assert 'type={showPw ? "text" : "password"}' in s
    assert "setShowPw((v) => !v)" in s
    assert '"Hide password" : "Show password"' in s


def test_the_eye_does_not_sit_on_top_of_the_text():
    """Without right padding a long password runs underneath the button."""
    s = _fe("app", "(auth)", "forgot-password", "page.tsx")
    i = s.index('id="new_password"')
    assert "pr-12" in s[i : i + 500]


def test_the_browser_is_told_it_is_choosing_a_new_password():
    s = _fe("app", "(auth)", "forgot-password", "page.tsx")
    assert 'autoComplete="new-password"' in s
