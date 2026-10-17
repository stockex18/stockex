"""Saturday, 17 Oct 2026: NIFTY games were open (the window only looked at the
clock) and every Zerodha instrument read +0.00% (Kite rolls `close` to the
day's own close at end of day). Both now follow the NSE calendar.
"""

import asyncio
import datetime as dt
import pathlib

import pytest

from app.core.exceptions import GameWindowClosedError
from app.services import holiday_service
from app.services import market_data_service as md
from app.services.games import common
from app.utils.time_utils import IST

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAT = dt.datetime(2026, 10, 17, 13, 0, tzinfo=IST)
FRI = dt.datetime(2026, 10, 16, 13, 0, tzinfo=IST)


@pytest.fixture
def no_holidays(monkeypatch):
    async def never(ex, d=None):
        return False

    monkeypatch.setattr(holiday_service, "is_market_holiday", never)


# ── games ────────────────────────────────────────────────────────────────


def test_nifty_games_refuse_bets_on_a_saturday(no_holidays):
    for key in ("niftyUpDown", "niftyNumber", "niftyBracket", "niftyJackpot"):
        with pytest.raises(GameWindowClosedError):
            asyncio.run(common.assert_nse_open_today(key, SAT))


def test_btc_games_run_on_a_saturday_and_nifty_on_a_weekday(no_holidays):
    asyncio.run(common.assert_nse_open_today("btcUpDown", SAT))
    asyncio.run(common.assert_nse_open_today("niftyUpDown", FRI))


def test_an_nse_holiday_closes_them_too(monkeypatch):
    async def holiday(ex, d=None):
        return ex == "NSE"

    monkeypatch.setattr(holiday_service, "is_market_holiday", holiday)
    with pytest.raises(GameWindowClosedError):
        asyncio.run(common.assert_nse_open_today("niftyUpDown", FRI))


def test_every_bet_gate_asks():
    calls = {
        "updown_service.py": 2,  # place + modify
        "number_service.py": 2,
        "jackpot_service.py": 2,
        "bracket_service.py": 1,
    }
    for f, n in calls.items():
        src = (ROOT / "app/services/games" / f).read_text(encoding="utf-8")
        assert src.count("await assert_nse_open_today(") == n, f


# ── weekend day-change ───────────────────────────────────────────────────


@pytest.fixture
def weekend(monkeypatch, no_holidays):
    import app.utils.time_utils as tu

    monkeypatch.setattr(tu, "now_ist", lambda: SAT)
    store = {}

    async def cget(k):
        return store.get(k)

    async def cset(k, v, ttl_sec=None):
        store[k] = v

    monkeypatch.setattr(md, "cache_get", cget)
    monkeypatch.setattr(md, "cache_set", cset)
    md._SESSION_BASE.clear()
    md._session_base_pending.clear()
    monkeypatch.setattr(md, "_SESSION_BASE_DAY", None)

    from app.services.zerodha_service import zerodha

    async def hist(token, frm, to, interval):
        assert interval == "day"
        return [{"close": 22900.0}, {"close": 23000.0}, {"close": 23146.15}]  # Wed, Thu, Fri

    monkeypatch.setattr(zerodha, "get_historical", hist)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s: real_sleep(0))  # skip the rate-limit gap


def _q(ltp, prev):
    return {"token": "256265", "ltp": ltp, "prev_close": prev, "change": ltp - prev, "change_pct": 0.0}


def test_on_a_saturday_the_change_is_fridays(weekend):
    async def run():
        first = await md.with_last_session_change(_q(23146.15, 23146.15), "256265")
        await asyncio.sleep(0)  # let the background fetch land
        for _ in range(5):
            await asyncio.sleep(0)
        return first, await md.with_last_session_change(_q(23146.15, 23146.15), "256265")

    first, later = asyncio.run(run())
    assert first["change_pct"] == 0.0  # the first paint before the fetch
    assert later["prev_close"] == 23000.0
    assert later["change"] == 146.15
    assert later["change_pct"] == 0.64


def test_a_moving_price_is_left_alone(weekend):
    q = _q(23150.0, 23146.15)
    assert asyncio.run(md.with_last_session_change(q, "256265")) is q


def test_a_weekday_is_left_alone(monkeypatch, no_holidays):
    import app.utils.time_utils as tu

    monkeypatch.setattr(tu, "now_ist", lambda: FRI)
    q = _q(23146.15, 23146.15)
    assert asyncio.run(md.with_last_session_change(q, "256265")) is q


def test_the_option_chain_does_not_fetch_baselines():
    src = (ROOT / "app/api/v1/user/option_chain.py").read_text(encoding="utf-8")
    assert "get_display_quote(l.token, session_change=False)" in src
