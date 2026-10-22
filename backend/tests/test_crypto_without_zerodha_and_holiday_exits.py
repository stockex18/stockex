"""Two weekend / holiday fixes (22 Oct).

1. Crypto trades without Zerodha. The "Zerodha feed disconnected" gate asked
   `is_usd_quoted_segment` (now always False), so BTCUSD orders were refused
   all weekend while Binance was quoting them live. It now gates only
   instruments Zerodha prices — Kite tokens are pure integers.
2. An NSE holiday closes NSE / F&O exits and opens. On Dussehra (20 Oct)
   "Square off all" closed NIFTY / BANKNIFTY futures and RELIANCE at the
   frozen previous close, and NSE orders still opened.
"""

import asyncio
import datetime as dt
import inspect
import pathlib

import pytest

from app.api.v1.user import positions
from app.services import holiday_service, order_validator
from app.utils.time_utils import IST

ROOT = pathlib.Path(__file__).resolve().parents[1]
DUSSEHRA_11AM = dt.datetime(2026, 10, 20, 11, 0, tzinfo=IST)
WEDNESDAY_11AM = dt.datetime(2026, 10, 21, 11, 0, tzinfo=IST)


def test_only_kite_tokens_wait_for_zerodha():
    src = inspect.getsource(order_validator.validate)
    assert '_z_fed = str(getattr(instrument, "token", "") or "").isdigit()' in src
    assert not "CRYPTO_BTCUSD".isdigit() and "256265".isdigit()


@pytest.fixture
def clock(monkeypatch):
    import app.utils.time_utils as tu

    def at(when, nse_holiday):
        monkeypatch.setattr(tu, "now_ist", lambda: when)

        async def holiday(ex, d=None):
            return nse_holiday and ex == "NSE"

        monkeypatch.setattr(holiday_service, "is_market_holiday", holiday)

        async def no_control(row):
            return True  # the admin's window says "open" — must not beat the calendar

        import app.services.market_control_service as mcs

        monkeypatch.setattr(mcs, "market_control_open", no_control)
        return lambda seg: asyncio.run(positions._is_segment_market_open_now(seg))

    return at


def test_on_an_nse_holiday_nse_and_fno_exits_wait(clock):
    open_now = clock(DUSSEHRA_11AM, nse_holiday=True)
    for seg in ("NFO", "NSE_FUT", "NSE_EQ", "BFO"):
        assert open_now(seg) is False, seg


def test_the_same_day_mcx_crypto_and_forex_still_close(clock):
    open_now = clock(DUSSEHRA_11AM, nse_holiday=True)
    for seg in ("MCX_FUT", "CRYPTO_SPOT", "FOREX"):
        assert open_now(seg) is True, seg


def test_a_normal_weekday_is_untouched(clock):
    open_now = clock(WEDNESDAY_11AM, nse_holiday=False)
    assert open_now("NFO") is True


def test_new_nse_orders_are_refused_on_a_holiday():
    src = inspect.getsource(order_validator.validate)
    assert "is closed today (holiday). Place AMO instead." in src
    i = src.index("Exchange holiday (runs EVEN under ALLOW_TRADE_AT_LAST_PRICE)")
    assert i < src.index("_allow_last_price = bool(")  # before the 24x7 bypass
