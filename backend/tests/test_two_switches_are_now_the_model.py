"""The admin fund-cap and the per-trade admin-book are not switches any more.

Both used to be live super-admin kill-switches, with cards on the Sub-admins
page and a Turn OFF button each:

    Admin fund-cap (float)          [ON]   [Turn OFF]
    Per-trade admin-book (SA↔admin) [ON]   [Turn OFF]

Operator: "dono ka ON kar do code me se hi, UI se hata do."

They are how the platform works, not modes. An admin funding users past the
float the super-admin gave them, and closing trades that stop booking the
house result and the super-admin's share — neither should be one click away,
and a switch only ever meant to sit in one position is a way to end up in the
other one.

Hiding the cards would not have been enough. A hidden endpoint is still an
endpoint, and the admin-book PUT changed where real money went on every
closing trade. The endpoints are gone, not hidden, so nothing holding a
super-admin token can flip either one while the UI no longer shows that it
has been.
"""

from __future__ import annotations

import asyncio
import inspect

from app.main import app
from app.services.admin_book_service import is_admin_book_enabled
from app.services.admin_fund_service import is_admin_float_enabled


def _routes() -> list[str]:
    return [getattr(r, "path", "") for r in app.routes]


# ── always on ─────────────────────────────────────────────────────────
def test_the_fund_cap_is_always_on():
    assert asyncio.run(is_admin_float_enabled()) is True


def test_the_admin_book_is_always_on():
    assert asyncio.run(is_admin_book_enabled()) is True


def test_neither_reads_a_stored_value_any_more():
    """A leftover PlatformSetting row from before this change must not be able
    to turn the feature back off."""
    for fn in (is_admin_float_enabled, is_admin_book_enabled):
        src = inspect.getsource(fn)
        assert "PlatformSetting" not in src, fn.__name__
        assert "setting_value" not in src, fn.__name__


def test_they_stay_behind_one_function_each():
    """Not inlined at the call sites. Every caller routes through these, so
    the rule is written in one place — and turning either back into a real
    toggle stays a one-line change."""
    for fn in (is_admin_float_enabled, is_admin_book_enabled):
        assert inspect.iscoroutinefunction(fn), fn.__name__


# ── the switches are gone, not hidden ─────────────────────────────────
def test_the_toggle_endpoints_no_longer_exist():
    for path in (
        "/api/v1/admin/settings/admin-float",
        "/api/v1/admin/settings/admin-float/enabled",
        "/api/v1/admin/settings/admin-book",
        "/api/v1/admin/settings/admin-book/enabled",
    ):
        assert path not in _routes(), path


def test_the_sa_earnings_routes_are_untouched():
    """`admin-book` also prefixes the SA Earnings reporting routes. Removing
    the toggle must not have taken the report with it."""
    paths = _routes()
    assert "/api/v1/admin/admin-book/report" in paths
    assert "/api/v1/admin/admin-book/transactions" in paths


def test_the_dead_env_flag_is_gone():
    """`ADMIN_FLOAT_ENABLED` was the env default the resolver fell back to.
    Nothing reads it now, and a setting that does nothing is worse than no
    setting — someone will set it and expect something to happen."""
    from app.core.config import settings

    assert not hasattr(settings, "ADMIN_FLOAT_ENABLED")


# ── what they switch on is still wired up ─────────────────────────────
def test_the_fund_cap_still_gates_admin_funding():
    from app.services import admin_fund_service

    src = inspect.getsource(admin_fund_service)
    assert src.count("await is_admin_float_enabled()") >= 2


def test_the_admin_book_still_gates_per_trade_booking():
    from app.services import admin_book_service

    src = inspect.getsource(admin_book_service)
    assert "await is_admin_book_enabled()" in src
