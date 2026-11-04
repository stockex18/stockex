"""MCX trades until 23:55 IST (operator, 3 Nov). The close was hardcoded at
23:30 in the open gate, the exit gate and the feed-health window; all three
now read time_utils.MCX_CLOSE, so there is one number to change."""

import asyncio
import inspect
from datetime import datetime, time

from app.api.v1.user import positions
from app.services import holiday_service, market_control_service, order_validator, zerodha_service
from app.utils import time_utils


def test_mcx_closes_at_2355():
    assert time_utils.MCX_CLOSE == time(23, 55)


def test_exit_gate_is_open_at_2350_and_shut_at_2356(monkeypatch):
    async def no(*_a, **_kw):
        return False

    async def no_opinion(*_a, **_kw):
        return None

    monkeypatch.setattr(holiday_service, "is_market_holiday", no)
    monkeypatch.setattr(market_control_service, "market_control_open", no_opinion)

    def at(hh, mm):
        # A Tuesday, so the weekend check passes.
        monkeypatch.setattr(time_utils, "now_ist", lambda: datetime(2026, 11, 3, hh, mm))
        return asyncio.run(positions._is_segment_market_open_now("MCX_FUTURE", "GOLD26DECFUT"))

    assert at(23, 50) is True
    assert at(23, 56) is False


def test_open_gate_and_feed_window_read_the_one_constant():
    assert "MCX_OPEN <= ist.time() <= MCX_CLOSE" in inspect.getsource(order_validator)
    assert "<= MCX_CLOSE" in inspect.getsource(zerodha_service.ZerodhaService._feed_expected_now)
