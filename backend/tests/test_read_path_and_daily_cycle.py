"""Two rules that finish the "prices come from the database" design.

1. A Kite REST call belongs to the FEED, never to a user's request. Warming a
   token that has no websocket tick yet is the feed loop's job; doing it while
   somebody waits for a quote put a ~2 s Kite round-trip inside the request.
   Production logged 6,078 `zerodha_overlay_timeout` — two seconds of a
   two-core event loop, each, for a price the mirror already held.

2. The daily reset runs on the CLOCK, not on the Kite token renewal. That is
   not a style preference: the token has failed to renew 484 times running on
   this deployment, and on the days it works it has landed as late as 09:12 —
   three minutes before the open. Hanging the reset off it means the reset
   either never happens or happens mid-session.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.services import daily_feed_cycle as dc
from app.services import market_data_service as mds


# ── 1. the read path ──────────────────────────────────────────────────
def test_the_overlay_can_be_told_not_to_call_kite():
    assert "allow_rest" in inspect.signature(mds._overlay_all).parameters


def test_both_request_paths_turn_it_off():
    """`get_quote` and `get_quotes` are what every user-facing quote goes
    through. Either one left on puts Kite back in the request."""
    for fn in (mds.get_quote, mds.get_quotes):
        src = inspect.getsource(fn)
        assert "_overlay_all(" in src
        assert "allow_rest=False" in src, fn.__name__


def test_the_feed_loop_keeps_it_on():
    """Something has to warm a newly added instrument. That is the feed's job
    and it is not on anybody's request path."""
    src = inspect.getsource(mds.tick_loop)
    assert "_overlay_all(token, base)" in src
    assert "allow_rest=False" not in src


def test_the_flag_still_respects_the_negative_cache():
    """The per-token REST skip window predates this and still applies — the
    new flag narrows, it does not replace."""
    src = inspect.getsource(mds._overlay_all)
    assert "_allow_rest = allow_rest and _now >= _zerodha_rest_skip.get(token, 0.0)" in src


def test_a_request_still_gets_a_price_from_the_mirror():
    """Turning REST off must not leave the request with nothing — the whole
    point is that the feed already stored it."""
    src = inspect.getsource(mds.get_quote)
    assert "_read_mdlive(token)" in src
    assert "_attach_last_quote" in src


# ── 2. the daily cycle ────────────────────────────────────────────────
def test_it_runs_before_the_earliest_market_opens():
    """MCX opens 09:00. Both jobs need to be done and settled by then."""
    assert dc.REBUILD_AT.hour == 7 and dc.REBUILD_AT.minute == 30
    assert dc.SWEEP_AT.hour == 8 and dc.SWEEP_AT.minute == 0
    assert dc.SWEEP_AT < dc.REBUILD_AT.replace(hour=9)


def test_it_is_not_hung_off_the_kite_token():
    """The CODE must not reach for the token — the docstring says why, so
    strip it before checking or the explanation trips its own test."""
    src = inspect.getsource(dc)
    body = src.replace(dc.__doc__ or "", "")
    for word in ("access_token", "accessToken", "tokenExpiry", "renew_access"):
        assert word not in body, word
    assert "REBUILD_AT" in body and "SWEEP_AT" in body


def test_a_window_is_wide_enough_to_survive_a_restart():
    """A minute-wide window would skip the day entirely if the worker happened
    to be restarting on it."""
    assert dc._WINDOW_MIN >= 10
    now = datetime.now(dc.IST).replace(hour=7, minute=35, second=0, microsecond=0)
    assert dc._in_window(now, dc.REBUILD_AT)


def test_outside_the_window_nothing_runs():
    now = datetime.now(dc.IST).replace(hour=11, minute=0, second=0, microsecond=0)
    assert not dc._in_window(now, dc.REBUILD_AT)
    assert not dc._in_window(now, dc.SWEEP_AT)


def test_each_job_runs_at_most_once_a_day():
    """The loop ticks every minute inside a twenty-minute window — without the
    day guard the rebuild would run twenty times."""
    src = inspect.getsource(dc.daily_feed_cycle_loop)
    assert "done_rebuild != day" in src and "done_sweep != day" in src
    assert 'day = now.strftime("%Y-%m-%d")' in src


@pytest.mark.asyncio
async def test_a_rebuild_failure_leaves_yesterdays_universe_alone(monkeypatch):
    """An empty universe is not a degraded platform, it is a stopped one —
    every open position unpriced and the risk enforcer blind."""
    async def _boom(*a, **k):
        raise RuntimeError("catalog cold")

    monkeypatch.setattr("app.services.core_feed_warm.warm_core_feed_once", _boom)
    monkeypatch.setattr(
        "app.services.market_data_service.ensure_open_position_subscriptions", _boom
    )
    out = await dc.rebuild_once()
    assert out == {"core": 0, "positions": 0}


def test_the_rebuild_never_unsubscribes_anything():
    """It only ever warms. Nothing in this path can take a token off the feed."""
    src = inspect.getsource(dc)
    for word in ("unsubscribe", "clear()", "subscribedInstruments = "):
        assert word not in src, word


def test_the_sweep_is_the_tick_stores_own_drop():
    """One implementation of retention, not two that can disagree."""
    assert "drop_old_collections" in inspect.getsource(dc.sweep_once)


def test_a_bad_day_does_not_stop_the_loop():
    src = inspect.getsource(dc.daily_feed_cycle_loop)
    assert "except Exception" in src and "daily_feed_cycle_iter_failed" in src


def test_the_loop_is_started_where_the_feed_is():
    from app import main

    src = inspect.getsource(main)
    assert "daily_feed_cycle" in src
    assert "daily_feed_cycle_loop, interval_sec=60.0" in src
