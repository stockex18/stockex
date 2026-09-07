"""An illiquid F&O contract is not a dead one.

Operator, mid-session: "last ka closing show ho raha kuch time ke liye ...
achanak se flicker se clearing aa rahi, last day ki" — and then, narrowing it:
"ye FNO me hi ho raha, future option me".

Only the worker holding `leader:feed` runs the tick loop, so the other four
gunicorn workers have a permanently-cold `_state` and read prices out of the
leader's `mdlive` mirror. The tick loop refused to mirror anything whose
exchange stamp was more than 10 minutes old.

That threw out the wrong thing. Ten minutes is nothing for an option. Measured
against the live book mid-session:

    TYPE   subscribed   in mirror   MISSING
    CE        110           2         108
    PE        104           0         104
    EQ        115          18          97
    FUT        43          29          14

212 of 214 option contracts were absent. For those, the leader kept serving its
held price from `_state` while every other worker fell through to `mdlast` and
answered with the PREVIOUS DAY'S CLOSE. The favourites list polls every 2 s and
lands on a different worker each time, so the live price and yesterday's close
alternated on screen — which is what "flicker" meant, and why it looked like
F&O only: the large caps and index futures print often enough to stay inside
ten minutes.

The gate's own comment always said "has not traded THIS SESSION". It just was
not asking that. Now it does, so there is no threshold left to tune.
"""

from __future__ import annotations

import inspect
import time

from app.services.market_data_service import _mirrorable


def test_a_fresh_tick_is_mirrored():
    assert _mirrorable({"exchange_timestamp": time.time()}) is True


def test_an_illiquid_contract_is_still_mirrored():
    """The case the old 10-minute cap dropped. The leader serves this price
    either way — the workers have to agree with it."""
    assert _mirrorable({"exchange_timestamp": time.time() - 660}) is True
    assert _mirrorable({"exchange_timestamp": time.time() - 4 * 3600}) is True


def test_a_previous_session_is_not_mirrored():
    """The reason the gate exists: the tick loop rewrites the key every second,
    so a 30 s TTL never lapses and an expired or never-opened contract would
    look live for ever."""
    assert _mirrorable({"exchange_timestamp": time.time() - 30 * 3600}) is False


def test_a_feed_with_no_exchange_clock_is_always_mirrored():
    """Infoway crypto / forex carry no exchange stamp. There is nothing to
    judge, and blanking them would take those segments off the screen."""
    assert _mirrorable({}) is True
    assert _mirrorable({"exchange_timestamp": 0}) is True
    assert _mirrorable({"exchange_timestamp": None}) is True


def test_a_broken_stamp_does_not_blank_the_feed():
    """Fail towards showing a price. A clock problem must not take the whole
    mirror down."""
    assert _mirrorable({"exchange_timestamp": "abc"}) is True
    assert _mirrorable({"exchange_timestamp": float("nan")}) is True


# ── it is wired in, and the old threshold is gone ─────────────────────
def test_the_tick_loop_uses_it():
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.tick_loop)
    assert "if not _mirrorable(q):" in src


def test_the_fixed_age_cap_is_gone():
    """A number to tune is what produced this. If it comes back, so does the
    flicker."""
    import app.services.market_data_service as mds

    assert not hasattr(mds, "_MIRROR_MAX_AGE_SEC")
    assert "_MIRROR_MAX_AGE_SEC" not in inspect.getsource(mds)


def test_a_zero_priced_tick_is_still_never_mirrored():
    """Separate guard, and it must stay — mirroring ltp 0 would push an empty
    price to every other worker."""
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.tick_loop)
    assert 'if float(q.get("ltp") or 0) <= 0:' in src


def test_the_batch_read_still_prefers_the_mirror():
    """The other half of this fix. `get_quotes` is what the favourite list and
    the positions screen call; without the mirror read it would go straight to
    the cold path again."""
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.get_quotes)
    assert "mirror = await get_quote_batch_mdlive(tokens)" in src


def test_the_age_still_travels_with_the_price():
    """Mirroring a held price is only safe because the consumer can tell it is
    held. `_mark_freshness` re-derives `age_sec` / `stale` on every read."""
    from app.services import market_data_service as mds

    assert "_mark_freshness" in inspect.getsource(mds.get_quotes)


# ── the session range has to travel with the price ────────────────────
def test_the_tick_carries_the_session_range():
    """Operator, straight after: "high low jo show hote hai usko bhi sahi se
    karna".

    The stream published only the price. A screen's high/low therefore came
    from the one-off REST seed at page load and never moved again, so the range
    went stale within minutes of opening — and on a cold worker that seed had
    itself been the PREVIOUS day's range. Both halves are fixed: the mirror
    carries the whole quote, and the range now rides every tick.
    """
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.tick_loop)
    for field in ("high", "low", "open", "prev_close"):
        assert f'"{field}": q.get("{field}")' in src, field


def test_the_mirror_stores_the_whole_quote_not_just_the_price():
    """`get_quote_batch_mdlive` is what a cold worker answers from, so a
    price-only mirror would leave the range to the stale fallback again."""
    from app.services import market_data_service as mds

    assert "mdlive_items.append((token, q))" in inspect.getsource(mds.tick_loop)
