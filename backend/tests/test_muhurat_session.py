"""Muhurat / special sessions. A day row with a start and end time is that
exchange's ONLY session, weekend or not, and every gate asks holiday_service
first: order entry, user exit, pending orders, SL/TP/stop-out, the carry sweep
and the quote freeze. Before this, Sunday's session was refused by six of the
seven gates on "weekend" alone."""

import asyncio
import inspect
from datetime import datetime, time, timedelta, timezone

from app.api.v1.user import positions
from app.services import (
    holiday_service,
    market_control_service,
    market_data_service,
    matching_engine,
    order_validator,
    position_service,
    risk_enforcer,
)
from app.utils import time_utils

IST = timezone(timedelta(hours=5, minutes=30))
SESSION = (time(14, 20), time(15, 30))


def _at(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=IST)


def test_inside_and_outside_the_session():
    assert holiday_service.session_closed(SESSION, _at(2026, 11, 8, 14, 19)) is True
    assert holiday_service.session_closed(SESSION, _at(2026, 11, 8, 14, 20)) is False
    assert holiday_service.session_closed(SESSION, _at(2026, 11, 8, 15, 29, 59)) is False
    assert holiday_service.session_closed(SESSION, _at(2026, 11, 8, 15, 30)) is True  # shut AT the end
    # The risk enforcer's wait for a real tick after the open.
    assert holiday_service.session_closed(SESSION, _at(2026, 11, 8, 14, 20, 30), 60) is True
    assert holiday_service.session_closed(SESSION, _at(2026, 11, 8, 14, 21, 1), 60) is False


def test_user_exit_follows_the_session_on_a_sunday(monkeypatch):
    sessions = {("NSE", "2026-11-08"): SESSION}

    async def special(ex, d=None):
        return sessions.get((ex, d.isoformat()))

    async def no(*_a, **_kw):
        return False

    async def no_opinion(*_a, **_kw):
        return None

    monkeypatch.setattr(holiday_service, "special_session", special)
    monkeypatch.setattr(holiday_service, "is_market_holiday", no)
    monkeypatch.setattr(market_control_service, "market_control_open", no_opinion)

    def open_at(*when, seg="NSE_INDEX_OPTION_BUY"):
        monkeypatch.setattr(time_utils, "now_ist", lambda: _at(*when))
        return asyncio.run(positions._is_segment_market_open_now(seg, "NIFTY"))

    assert open_at(2026, 11, 8, 9, 0) is False  # Sunday, before the session
    assert open_at(2026, 11, 8, 14, 30) is True  # inside it
    assert open_at(2026, 11, 8, 15, 31) is False  # after it
    assert open_at(2026, 11, 8, 14, 30, seg="MCX_FUTURE") is False  # MCX set nothing
    assert open_at(2026, 11, 15, 14, 30) is False  # an ordinary Sunday


def test_every_gate_asks_for_the_special_session_first():
    assert "_ss is None" in inspect.getsource(order_validator)  # market control + weekend skipped
    assert "special_session" in inspect.getsource(matching_engine)  # pending LIMIT / SL
    assert "special_session" in inspect.getsource(risk_enforcer)  # SL / TP / stop-out
    assert "special_session" in inspect.getsource(position_service.intraday_to_carry_loop)
    assert "special_session_closed" in inspect.getsource(market_data_service._session_over)
