"""The super-admin's platform-wide OTP switch (Admin → Platform settings).

ON (and before anyone touches it): signup asks for a texted code where it did
before, and forgot-password texts its code. OFF: signup needs no code, nothing
is texted, and forgot-password says to contact support — a password is never
reset without a code. A switch that cannot be read counts as not set, so OTP
falls back ON; it can fail to turn off, never silently turn off.
"""

import asyncio
import pathlib
import types

import pytest

from app.api.v1.admin import settings as admin_settings
from app.api.v1.user import auth as api
from app.core.config import settings
from app.core.exceptions import ValidationFailedError
from app.schemas.auth import ForgotPasswordRequest, OtpRequest
from app.services import sms_service as sms

ROOT = pathlib.Path(__file__).resolve().parents[2]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def switch(monkeypatch):
    """Set the platform switch: True / False / None (never set)."""
    state = {"value": None}

    async def fake():
        return state["value"]

    monkeypatch.setattr(sms, "otp_switch", fake)
    monkeypatch.setattr(sms, "is_configured", lambda: True)

    def set_(v):
        state["value"] = v

    return set_


@pytest.fixture
def texts(monkeypatch):
    sent = []

    async def send(mobile, code):
        sent.append((mobile, code))

    async def issue(purpose, ident, **kw):
        return "1234"

    async def nobody_has_it(email, mobile, role=None):
        return None

    async def find(identifier, roles=None):
        return types.SimpleNamespace(id="u1", email="a@b.c", mobile="9876543210")

    monkeypatch.setattr(sms, "send_otp", send)
    monkeypatch.setattr(api, "issue_otp", issue)
    monkeypatch.setattr(api.user_service, "email_or_mobile_taken", nobody_has_it)
    monkeypatch.setattr(api.user_service, "find_by_identifier", find)
    return sent


class _Reg:
    email = "new@example.com"
    mobile = "9876543296"
    otp = None


# ── the switch decides, the env var is only the default ──────────────────


@pytest.mark.parametrize("env", [True, False])
def test_switched_off_signup_needs_no_code_whatever_the_env_says(switch, monkeypatch, env):
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", env)
    switch(False)
    run(api._require_register_otp(_Reg()))  # no code, no error
    assert run(api.signup_config()).data == {"sms_otp": False, "reset_by_sms": False}


@pytest.mark.parametrize("env", [True, False])
def test_switched_on_signup_needs_a_code_whatever_the_env_says(switch, monkeypatch, env):
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", env)
    switch(True)
    with pytest.raises(ValidationFailedError):
        run(api._require_register_otp(_Reg()))
    assert run(api.signup_config()).data == {"sms_otp": True, "reset_by_sms": True}


def test_never_set_keeps_todays_behaviour(switch, monkeypatch):
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", True)
    switch(None)
    assert run(api.signup_config()).data == {"sms_otp": True, "reset_by_sms": True}


# ── OFF means nothing is texted ──────────────────────────────────────────


def test_switched_off_a_signup_code_is_not_texted(switch, texts):
    switch(False)
    with pytest.raises(ValidationFailedError):
        run(api.request_otp(OtpRequest(purpose="register", identifier="9876543296")))
    assert texts == []


def test_switched_off_forgot_password_sends_nothing_and_says_contact_support(switch, texts):
    switch(False)
    with pytest.raises(ValidationFailedError) as e:
        run(api.forgot_password(ForgotPasswordRequest(identifier="9876543210")))
    assert "contact support" in str(e.value).lower()
    assert texts == []


def test_switched_on_forgot_password_still_texts_the_code(switch, texts):
    switch(True)
    run(api.forgot_password(ForgotPasswordRequest(identifier="9876543210")))
    assert texts == [("9876543210", "1234")]


# ── the switch itself ────────────────────────────────────────────────────


def test_an_unreadable_switch_counts_as_not_set_so_otp_stays_on(monkeypatch):
    class Boom:
        setting_key = "x"

        @staticmethod
        async def find_one(*a, **k):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(sms, "PlatformSetting", Boom)
    assert run(sms.otp_switch()) is None
    assert run(sms.reset_otp_enabled()) is True
    monkeypatch.setattr(settings, "SMS_OTP_ON_REGISTER", True)
    assert run(sms.register_otp_required()) is True


def test_only_the_super_admin_can_flip_it():
    src = (ROOT / "backend/app/api/v1/admin/settings.py").read_text(encoding="utf-8")
    guard = src[src.index("async def update_platform_setting") :][:900]
    assert '"security.sms_otp"' in guard
    assert "_require_super_admin(admin)" in guard
    assert sms.OTP_SWITCH_KEY.startswith("security.sms_otp")


def test_a_non_super_admin_is_refused():
    admin = types.SimpleNamespace(role="ADMIN", id="a1")
    payload = types.SimpleNamespace(setting_value=False)
    with pytest.raises(Exception) as e:
        run(admin_settings.update_platform_setting(sms.OTP_SWITCH_KEY, payload, admin))
    assert getattr(e.value, "status_code", None) == 403


# ── the apps ─────────────────────────────────────────────────────────────


def test_the_admin_page_has_the_switch_for_the_super_admin_only():
    src = (ROOT / "frontend-admin/app/(admin)/settings/platform/page.tsx").read_text(encoding="utf-8")
    assert '"security.sms_otp_enabled"' in src
    card = src[src.index("function OtpSwitchCard") :]
    assert '=== "SUPER_ADMIN"' in card[:1500]
    # Default ON when the row has never been written.
    assert "row ? Boolean(row.value) : true" in card


def test_forgot_password_page_says_contact_support_when_reset_by_sms_is_off():
    src = (ROOT / "frontend-user/app/(auth)/forgot-password/page.tsx").read_text(encoding="utf-8")
    assert "reset_by_sms === false" in src
    assert "contact support" in src.lower()
