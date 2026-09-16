"""A holiday on the admin's calendar means no session — for everything.

Operator: "market band tha, holiday tha us din — phir kaise NIFTY ke saare
position close ho gaye?" The calendar existed (admin screen + CRUD since day
one) but no trading code ever read it, so a holiday ran like a full day: the
risk enforcer priced stop-outs off the previous session's frozen tick, the
15:41 sweep squared off, and an expiring contract settled at a price the
exchange never printed.
"""

from __future__ import annotations

import asyncio
import inspect

from app.services import expiry_cleanup, holiday_service, position_service, risk_enforcer


def _run(coro):
    return asyncio.run(coro)


class _Row:
    pass


def _fake_calendar(monkeypatch, *, holiday: bool, seen: list | None = None):
    from app.models.holiday import TradingHoliday

    async def find_one(query):
        if seen is not None:
            seen.append(query)
        return _Row() if holiday else None

    monkeypatch.setattr(TradingHoliday, "find_one", staticmethod(find_one))
    holiday_service.clear_cache()


def test_a_marked_day_reads_as_a_holiday(monkeypatch):
    _fake_calendar(monkeypatch, holiday=True)
    from datetime import date

    assert _run(holiday_service.is_market_holiday("NSE", date(2026, 9, 8))) is True


def test_an_unmarked_day_is_a_normal_session(monkeypatch):
    _fake_calendar(monkeypatch, holiday=False)
    from datetime import date

    assert _run(holiday_service.is_market_holiday("NSE", date(2026, 9, 8))) is False


def test_only_full_day_rows_count(monkeypatch):
    # A half-day / Muhurat session is still a session, so the query must ask
    # for full-day rows only.
    seen: list = []
    _fake_calendar(monkeypatch, holiday=False, seen=seen)
    from datetime import date

    _run(holiday_service.is_market_holiday("NSE", date(2026, 9, 8)))
    assert seen and seen[0].get("is_full_day") is True


def test_an_equity_holiday_filed_under_any_of_its_names_still_counts(monkeypatch):
    seen: list = []
    _fake_calendar(monkeypatch, holiday=False, seen=seen)
    from datetime import date

    _run(holiday_service.is_market_holiday("NSE", date(2026, 9, 8)))
    assert set(seen[0]["exchange"]["$in"]) == {"NSE", "BSE", "NFO", "BFO"}
    holiday_service.clear_cache()
    seen.clear()
    _run(holiday_service.is_market_holiday("MCX", date(2026, 9, 8)))
    assert seen[0]["exchange"]["$in"] == ["MCX"]


def test_the_24x7_feeds_never_observe_a_holiday():
    assert holiday_service.exchange_for_segment("CRYPTO_SPOT") is None
    assert holiday_service.exchange_for_segment("CDS_FUTURE") is None
    assert holiday_service.exchange_for_segment("MCX_FUT") == "MCX"
    assert holiday_service.exchange_for_segment("NFO_OPTION") == "NSE"


def test_a_lookup_failure_never_freezes_trading(monkeypatch):
    from app.models.holiday import TradingHoliday
    from datetime import date

    async def boom(_query):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(TradingHoliday, "find_one", staticmethod(boom))
    holiday_service.clear_cache()
    assert _run(holiday_service.is_market_holiday("NSE", date(2026, 9, 8))) is False


def test_the_risk_enforcer_treats_a_holiday_as_a_closed_session():
    src = inspect.getsource(risk_enforcer._enforce_for_user)
    assert "nse_holiday" in src and "mcx_holiday" in src
    # Checked inside the same helper that decides weekend / after-close.
    assert src.index("mcx_holiday = await") < src.index("def _segment_closed")


def test_the_1541_sweep_skips_a_holiday():
    src = inspect.getsource(position_service.intraday_to_carry_loop)
    assert "holiday_service.is_market_holiday(" in src
    # Before the per-group work, so neither the square-off nor the expiry
    # settlement it triggers can run.
    assert src.index("holiday_service.is_market_holiday(") < src.index("_rollover_already_done")


def test_the_hourly_expiry_sweep_skips_a_holiday():
    src = inspect.getsource(expiry_cleanup)
    assert "holiday_service.is_segment_holiday(" in src
    assert src.index("holiday_service.is_segment_holiday(") < src.index(
        "position_service.settle_expired_position(_pos)"
    )


def test_only_the_super_admin_may_edit_the_calendar():
    from app.api.v1.admin import settings as admin_settings

    for fn in (admin_settings.create_holiday, admin_settings.delete_holiday):
        src = inspect.getsource(fn)
        assert "_require_super_admin(admin)" in src, fn.__name__
        assert "holiday_service.clear_cache()" in src, fn.__name__
