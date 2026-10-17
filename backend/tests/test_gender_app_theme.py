"""The user app is pink for female clients and gold for everyone else."""

import pathlib
import types

from app.services import auth_service

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_login_payload_carries_gender():
    u = types.SimpleNamespace(
        id="1", user_code="CL1", email="a@b.co", mobile="9876543210", full_name="A",
        role=types.SimpleNamespace(value="CLIENT"), status=types.SimpleNamespace(value="ACTIVE"),
        is_demo=False, two_fa_enabled=False, must_change_password=False, gender="FEMALE",
        admin_permissions=None, pnl_share_pct=None, broker_permissions=None, assigned_broker_id=None,
    )
    assert auth_service._user_to_auth_out(u).gender == "FEMALE"


def test_gold_unless_female():
    css = (ROOT / "frontend-user/app/globals.css").read_text(encoding="utf-8")
    assert ':root:not([data-gender="FEMALE"]) {' in css
    assert ':root.dark:not([data-gender="FEMALE"]) {' in css
    gt = (ROOT / "frontend-user/components/common/GenderTheme.tsx").read_text(encoding="utf-8")
    assert 'if (gender === "FEMALE") el.setAttribute("data-gender", "FEMALE");' in gt
    assert "<GenderTheme />" in (ROOT / "frontend-user/app/providers.tsx").read_text(encoding="utf-8")
    assert "GENDER_THEME_SCRIPT" in (ROOT / "frontend-user/app/layout.tsx").read_text(encoding="utf-8")
