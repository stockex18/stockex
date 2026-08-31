"""No live feed, no new position.

Reported live: Zerodha was disconnected and orders still went through.

The 2-second freeze guard only runs when an exchange timestamp is available.
With the feed fully down there is no timestamp at ALL — nothing in
`ticks_by_token`, nothing mirrored into `mdlive` — so the strict branch was
skipped and control fell to a heuristic that asked the wrong question:

    _feed_live = _live_snap is not None

`mdlive` presence is not freshness. The tick loop rewrites every subscribed
token's key once a second from the last known quote, with a 30 s TTL, so a
frozen price keeps its key alive indefinitely and the order was allowed at
whatever price was last seen.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import order_validator


@pytest.fixture(scope="module")
def src() -> str:
    return inspect.getsource(order_validator.validate)


# -- the guard that was already there ----------------------------------
def test_a_frozen_feed_still_blocks_at_two_seconds(src):
    """The operator's original threshold — this one worked and stays."""
    assert "_FEED_FREEZE_MAX_AGE_SEC = 2.0" in src
    assert "_ex_age > _FEED_FREEZE_MAX_AGE_SEC" in src


# -- the hole this closes ----------------------------------------------
def test_no_exchange_time_at_all_now_blocks_an_open(src):
    """Not a quirk for a Zerodha-fed contract — it IS the feed being down."""
    tail = src[src.index("_zerodha_fed = not ("):]
    assert "if _zerodha_fed and not is_squareoff:" in tail
    assert "raise MarketClosedError" in tail


def test_the_message_says_what_the_operator_asked_for(src):
    assert "Please try after some time." in src


def test_presence_is_no_longer_the_only_test_for_a_zerodha_feed(src):
    """The block must come BEFORE the mdlive-presence heuristic, or presence
    would keep letting it through."""
    i = src.index("_zerodha_fed = not (")
    j = src.index("_feed_live = _live_snap is not None")
    assert i < j


# -- what must NOT be blocked ------------------------------------------
def test_exits_are_exempt(src):
    """A user must always be able to flatten, feed or no feed."""
    i = src.index("_zerodha_fed = not (")
    block = src[i:i + 400]
    assert "not is_squareoff" in block


def test_usd_quoted_feeds_keep_the_old_behaviour(src):
    """Infoway crypto / forex carry no exchange timestamp by design — blocking
    on its absence would stop those segments trading altogether."""
    i = src.index("_zerodha_fed = not (")
    block = src[i:i + 300]
    assert "is_usd_quoted_segment(segment_type)" in block
    assert "is_usd_quoted_segment(_inst_seg_now)" in block


def test_the_sixty_second_heuristic_survives_for_them(src):
    """It is the only signal those segments have left."""
    assert "_TICK_MAX_AGE_SEC = 60" in src
    assert "_live_snap = await _read_mdlive(instrument.token)" in src


# -- ordering of the whole ladder --------------------------------------
def test_the_session_check_still_comes_first(src):
    """A closed session should read as closed, not as a dead feed."""
    assert src.index("_SESSION_STALE_SEC") < src.index("_FEED_FREEZE_MAX_AGE_SEC")
    assert src.index("_ex_age > _SESSION_STALE_SEC") < src.index("_ex_age > _FEED_FREEZE_MAX_AGE_SEC")
