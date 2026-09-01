"""A held price must not read as a live one.

Reported live, and confirmed on production at 09:32 IST with the market open:

    AGE_s   LTP      HIGH   LOW
    2907    7328.0   0.0    0.0     <- 48 minutes old, served as live
    2178    7475.0   0.0    0.0
    129     7328.0   7350.0 7350.0

The tick loop rewrites every subscribed token's `ts` and its `mdlive` key once
a second from the last known quote. So a contract that had not traded since
before the open still looked fresh: new timestamp, 30 s TTL that never got a
chance to lapse, and a confident wrong number on screen.

Freshness therefore has to come from the EXCHANGE's clock, never from `ts`.
"""

from __future__ import annotations

import inspect
import time

import pytest

from app.services import market_data_service as mds


def _q(age_sec: float | None):
    if age_sec is None:
        return mds._mark_freshness({})
    return mds._mark_freshness({"exchange_timestamp": time.time() - age_sec})


# -- what counts as live -----------------------------------------------
def test_a_just_arrived_tick_is_live():
    assert _q(0.2)["stale"] is False


@pytest.mark.parametrize("age", [2.5, 30, 129, 2907])
def test_anything_past_the_threshold_is_stale(age):
    assert _q(age)["stale"] is True


def test_the_screen_and_the_fill_agree():
    """Same threshold the order validator blocks opens at, so a price the
    screen calls live is one the server will actually fill against."""
    assert mds._QUOTE_STALE_SEC == 2.0


def test_the_age_is_reported_so_callers_can_judge_for_themselves():
    assert _q(129)["age_sec"] == pytest.approx(129, abs=1)


# -- feeds with no exchange clock --------------------------------------
def test_a_feed_without_an_exchange_clock_is_not_called_stale():
    """Infoway crypto / forex carry no exchange timestamp. Marking them stale
    would blank those segments outright."""
    q = _q(None)
    assert q["age_sec"] is None
    assert q["stale"] is False


@pytest.mark.parametrize("bad", [0, "", None, "abc"])
def test_an_unusable_stamp_degrades_quietly(bad):
    q = mds._mark_freshness({"exchange_timestamp": bad})
    assert q["age_sec"] is None and q["stale"] is False


# -- the mirror that kept dead prices alive ----------------------------
def test_a_contract_that_never_traded_this_session_stops_being_mirrored():
    src = inspect.getsource(mds.tick_loop)
    assert "_age > _MIRROR_MAX_AGE_SEC" in src
    assert "continue" in src[src.index("_MIRROR_MAX_AGE_SEC"):]


def test_the_mirror_cutoff_is_well_past_a_quiet_contract():
    """It must catch a pre-session price without blanking an illiquid one that
    genuinely trades a few times an hour."""
    assert mds._MIRROR_MAX_AGE_SEC >= 600


def test_a_feed_with_no_clock_is_still_mirrored():
    """Judged only where an exchange clock exists — otherwise crypto/forex,
    which have none, would stop being published at all."""
    src = inspect.getsource(mds.tick_loop)
    assert "_age is not None and _age > _MIRROR_MAX_AGE_SEC" in src


# -- the signal reaches consumers --------------------------------------
def test_every_tick_carries_its_own_freshness():
    src = inspect.getsource(mds.tick_loop)
    assert '"age_sec": q.get("age_sec")' in src
    assert '"stale": q.get("stale")' in src


def test_both_quote_paths_are_stamped():
    """The warm mdlive path and the cold overlay path — a caller must not have
    to know which one served it."""
    src = inspect.getsource(mds.get_quote)
    assert src.count("_mark_freshness") == 2


def test_freshness_never_reads_the_loops_own_timestamp():
    """`ts` is rewritten every second whether the price moved or not — reading
    it is what made a frozen quote look live."""
    src = inspect.getsource(mds._mark_freshness)
    assert "exchange_timestamp" in src
    assert 'q.get("ts")' not in src
