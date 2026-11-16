"""NIFTY games run during a special NSE session (Diwali Muhurat).

8 Nov 2026 was a Sunday with a Muhurat session 14:20-15:30 in the holiday
calendar. Trading honoured it, but the games only knew "weekend or full-day
holiday", so every NIFTY game stayed closed. Now a special session opens the
NIFTY games for that day, with each game's times re-based onto the session.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace as Namespace

import pytest
import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from app.api.v1.user.games import settings as user_settings_api
from app.core.exceptions import GameWindowClosedError
from app.models._base import Exchange
from app.models.games.settings import GameConfig, GameSettings
from app.models.holiday import TradingHoliday
from app.services import holiday_service
from app.services.games import common
from app.utils import time_utils
from app.utils.time_utils import IST

MUHURAT = date(2026, 11, 8)  # Sunday
NORMAL_DAY = date(2026, 11, 10)  # Tuesday
PLAIN_SUNDAY = date(2026, 11, 15)
FULL_HOLIDAY = date(2026, 11, 24)  # Tuesday, marked a full-day holiday below


@pytest_asyncio.fixture
async def calendar(monkeypatch):
    await init_beanie(
        database=AsyncMongoMockClient()["games_ss"], document_models=[TradingHoliday, GameSettings]
    )
    holiday_service._cache.clear()
    holiday_service._session_cache.clear()
    for ex in (Exchange.NSE, Exchange.MCX):
        await TradingHoliday(
            holiday_date=MUHURAT, exchange=ex, description="Diwali Muhurat trading",
            is_full_day=False, is_muhurat=True, open_time="14:20", close_time="15:30",
        ).insert()
    await TradingHoliday(holiday_date=FULL_HOLIDAY, exchange=Exchange.NSE, description="Holiday").insert()
    yield
    holiday_service._cache.clear()
    holiday_service._session_cache.clear()


def _at(d: date, hh: int, mm: int) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=IST)


# ── timing: the WHOLE session the admin entered ─────────────────────
UPDOWN = GameConfig(start_time="09:15:00", end_time="15:00:00", round_duration=900)
NUMBER = GameConfig(bidding_start_time="09:15:00", bidding_end_time="15:00:00",
                    result_time="15:45:00", max_bid_time="14:59:00")
BRACKET = GameConfig(bidding_start_time="09:15:00", bidding_end_time="15:30:00", result_time="15:30:00")
MUHURAT_SS = (time(14, 20), time(15, 30))


def test_every_game_runs_the_whole_muhurat_session():
    for key, cfg in (("niftyNumber", NUMBER), ("niftyJackpot", NUMBER), ("niftyBracket", BRACKET)):
        c = common.rebase_config(cfg, MUHURAT_SS, key)
        assert (c.bidding_start_time, c.bidding_end_time, c.result_time) == ("14:20:00", "15:30:00", "15:30:00"), key


def test_updown_rounds_fit_inside_the_session():
    u = common.rebase_config(UPDOWN, MUHURAT_SS, "niftyUpDown")
    # Rounds 14:20, 14:35, 14:50; the 14:50 round is decided by 15:05-15:20,
    # so betting closes at 15:05 and no round is decided after 15:30.
    assert (u.start_time, u.end_time) == ("14:20:00", "15:05:00")
    last_round_open = common.parse_hms(u.end_time)
    decided_at = (datetime.combine(MUHURAT, last_round_open) + timedelta(minutes=15)).time()
    assert decided_at <= MUHURAT_SS[1]


def test_timing_follows_whatever_session_the_admin_enters():
    ss = (time(18, 15), time(19, 15))
    u = common.rebase_config(UPDOWN, ss, "niftyUpDown")
    # Rounds 18:15, 18:30, 18:45 (the last decided by 19:00-19:15) -> betting closes 19:00.
    assert (u.start_time, u.end_time) == ("18:15:00", "19:00:00")
    n = common.rebase_config(NUMBER, ss, "niftyNumber")
    assert (n.bidding_start_time, n.bidding_end_time, n.result_time) == ("18:15:00", "19:15:00", "19:15:00")


def test_the_platform_close_setting_is_not_used(monkeypatch):
    # MARKET_CLOSE_TIME is the operator's trading cutoff (15:40 by default),
    # not part of the Muhurat timing.
    before = common.rebase_config(UPDOWN, MUHURAT_SS, "niftyUpDown")
    for close in ("15:30", "15:40", "16:00"):
        monkeypatch.setattr(time_utils.settings, "MARKET_CLOSE_TIME", close)
        assert common.rebase_config(UPDOWN, MUHURAT_SS, "niftyUpDown") == before
        assert common.rebase_config(NUMBER, MUHURAT_SS, "niftyNumber").result_time == "15:30:00"


def test_a_session_too_short_for_updown_leaves_it_shut():
    u = common.rebase_config(UPDOWN, (time(15, 10), time(15, 30)), "niftyUpDown")
    assert u.end_time == u.start_time  # no round fits -> betting never opens


def test_the_saved_config_is_not_changed():
    common.rebase_config(UPDOWN, MUHURAT_SS, "niftyUpDown")
    assert UPDOWN.start_time == "09:15:00"


# ── open / closed ─────────────────────────────────────────────────────
async def test_muhurat_sunday_is_open_for_nifty_games(calendar):
    assert await common.nse_closed_on(MUHURAT) is False
    await common.assert_nse_open_today("niftyUpDown", _at(MUHURAT, 14, 30))  # no raise


async def test_a_plain_sunday_still_refuses_nifty_bets(calendar):
    with pytest.raises(GameWindowClosedError):
        await common.assert_nse_open_today("niftyUpDown", _at(PLAIN_SUNDAY, 14, 30))


async def test_normal_days_are_unchanged(calendar):
    assert await common.nse_closed_on(NORMAL_DAY) is False
    assert await common.nse_closed_on(PLAIN_SUNDAY) is True
    assert await common.nse_closed_on(FULL_HOLIDAY) is True


async def test_btc_games_are_never_touched(calendar):
    await common.assert_nse_open_today("btcUpDown", _at(PLAIN_SUNDAY, 12, 0))  # no raise
    s = Namespace(games={"btcUpDown": GameConfig(start_time="00:00:00", end_time="22:30:00")})
    cfg = await common.effective_config(s, "btcUpDown", MUHURAT)
    assert cfg.start_time == "00:00:00"


# ── price logic: "is NIFTY trading now" ───────────────────────────────
async def test_price_logic_sees_the_muhurat_session(calendar):
    assert await common.nifty_market_open(_at(MUHURAT, 14, 30)) is True
    assert await common.nifty_market_open(_at(MUHURAT, 14, 0)) is False
    assert await common.nifty_market_open(_at(MUHURAT, 16, 0)) is False
    assert await common.nifty_market_open(_at(PLAIN_SUNDAY, 14, 30)) is False


async def test_price_logic_on_a_normal_day_is_unchanged(calendar):
    for hh, mm in ((9, 30), (14, 30), (16, 0)):
        at = _at(NORMAL_DAY, hh, mm)
        assert await common.nifty_market_open(at) is time_utils.is_market_open(at)


# ── a whole game day on the Muhurat Sunday ────────────────────────────
async def test_updown_windows_run_from_the_session_open(calendar):
    s = Namespace(games={"niftyUpDown": UPDOWN})
    cfg = await common.effective_config(s, "niftyUpDown", MUHURAT)
    now = _at(MUHURAT, 14, 25)
    w = common.window_number_for(now, cfg.start_time, cfg.round_duration)
    assert w == 1
    o, c = common.window_open_close_ist(now, cfg.start_time, cfg.round_duration, w)
    assert (o.time(), c.time()) == (time(14, 20), time(14, 35))
    # Settlement for that day uses that day's windows, whatever day it runs on.
    later = await common.effective_config(s, "niftyUpDown", "2026-11-08")
    assert later.start_time == "14:20:00"
    normal = await common.effective_config(s, "niftyUpDown", "2026-11-10")
    assert normal.start_time == "09:15:00"


async def test_the_user_settings_api_sends_the_days_times(calendar, monkeypatch):
    async def no_cache(*a, **k):
        return None

    monkeypatch.setattr(user_settings_api, "cache_get", no_cache)
    monkeypatch.setattr(user_settings_api, "cache_set", no_cache)
    monkeypatch.setattr(time_utils, "now_ist", lambda: _at(MUHURAT, 14, 30))
    data = (await user_settings_api.get_settings(user=None)).data
    assert data["nse_open_today"] is True
    assert data["nse_special_session"] == {"open": "14:20", "close": "15:30"}
    assert data["games"]["niftyUpDown"]["start_time"] == "14:20:00"
    assert data["games"]["btcUpDown"]["start_time"] == "00:00:00"

    monkeypatch.setattr(time_utils, "now_ist", lambda: _at(NORMAL_DAY, 10, 0))
    data = (await user_settings_api.get_settings(user=None)).data
    assert data["nse_open_today"] is True
    assert data["nse_special_session"] is None
    assert data["games"]["niftyUpDown"]["start_time"] == "09:15:00"
