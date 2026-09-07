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


# ── the mirror has to cover the whole feed, not one browser's view ────
def test_the_mirror_covers_every_token_the_feed_carries():
    """The other half, and the bigger one.

    `_state` is demand-driven — a row appears only when somebody ASKS for that
    token — and so is `_subscribed`, which fills from browser websocket
    subscribes. The tick loop mirrored the INTERSECTION, so `mdlive` held only
    what a browser had open that second: 14 of 372 measured mid-session, flat
    for two and a half minutes.

    That is why it showed on the contract you had just opened. The REST quote
    fires before the websocket subscribe lands, so the mirror held nothing, a
    cold worker fell through to `mdlast`, and the screen showed the previous
    day's close until the first tick corrected it. Large caps hid it because
    somebody else always had them open already.
    """
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.tick_loop)
    assert "for _tok in _feed_tokens():" in src
    assert "pending = list(_state.items())" in src
    assert "if token in _subscribed" not in src


def test_the_feed_token_set_reads_both_tickers():
    from app.services import market_data_service as mds

    src = inspect.getsource(mds._feed_tokens)
    assert "zerodha.ticks_by_token" in src
    assert "infoway.ticks" in src


def test_a_cold_ticker_does_not_take_the_loop_down():
    """It runs every second. An import or attribute problem in either ticker
    must degrade to 'nothing extra to mirror', never raise."""
    from app.services import market_data_service as mds

    assert mds._feed_tokens() == set() or isinstance(mds._feed_tokens(), set)
    assert inspect.getsource(mds._feed_tokens).count("except Exception") == 2


def test_the_websocket_fanout_is_still_only_what_is_watched():
    """Widening the MIRROR must not start publishing 372 tokens a second to
    subscribers who asked for five."""
    from app.services import market_data_service as mds

    src = inspect.getsource(mds.tick_loop)
    i = src.index("mdlive_items.append((token, q))")
    assert "if token not in _subscribed:" in src[i : i + 400]


# ── the fallback must never be days old ───────────────────────────────
def test_the_mirror_write_refreshes_the_display_fallback_too():
    """Operator: "there was an error in EICHERMOT at 2:55 pm, same like
    closing price for 2 seconds".

    `mdlast` is the fallback `_attach_last_quote` reaches for when there is no
    live price. It was written ONLY by `_persist_last_quote`, which sits on the
    slow quote path - so once a token started being served from the mirror that
    path stopped running for it and its `mdlast` froze. Measured mid-session
    against tokens the mirror was actively serving:

        median staleness  2,202 min (36.7 h)
        worst             8,403 min (5.8 days)

        BANKNIFTY26SEP56800CE   mdlast 1148.25   live 980.10

    So a single missed mirror read handed back a price from days ago and was
    gone again a beat later. Both keys are now written from the same tick, so
    the fallback is at worst one tick behind.
    """
    import inspect

    from app.services import market_data_service as mds

    src = inspect.getsource(mds._write_mdlive_batch)
    assert "_MDLIVE_KEY.format(token=token)" in src
    assert "_LAST_QUOTE_KEY.format(token=token)" in src


async def test_both_keys_are_written_for_a_priced_tick(monkeypatch):
    import json

    from app.services import market_data_service as mds

    ops: list = []

    class _Pipe:
        def set(self, k, v, ex=None):
            ops.append((k, json.loads(v), ex))

        async def execute(self):
            return []

    pipe = _Pipe()
    monkeypatch.setattr(
        "app.core.redis_client.get_redis",
        lambda: type("R", (), {"pipeline": lambda self, transaction=False: pipe})(),
    )
    await mds._write_mdlive_batch(
        [("123", {"ltp": 100.5, "high": 101, "low": 99, "open": 100, "prev_close": 98})]
    )
    keys = {k for k, _, _ in ops}
    assert keys == {"mdlive:123", "mdlast:123"}
    ttls = {k: ex for k, _, ex in ops}
    assert ttls["mdlive:123"] == mds._MDLIVE_TTL_SEC
    assert ttls["mdlast:123"] == mds._LAST_QUOTE_TTL_SEC


async def test_a_zero_priced_tick_never_reaches_the_fallback(monkeypatch):
    """Writing ltp 0 into `mdlast` would make the fallback itself blank, which
    is worse than a stale one."""
    import json

    from app.services import market_data_service as mds

    ops: list = []

    class _Pipe:
        def set(self, k, v, ex=None):
            ops.append((k, json.loads(v), ex))

        async def execute(self):
            return []

    pipe = _Pipe()
    monkeypatch.setattr(
        "app.core.redis_client.get_redis",
        lambda: type("R", (), {"pipeline": lambda self, transaction=False: pipe})(),
    )
    await mds._write_mdlive_batch([("456", {"ltp": 0, "high": 0, "low": 0})])
    assert {k for k, _, _ in ops} == {"mdlive:456"}


def test_the_fallback_still_refuses_to_become_a_tradeable_price():
    """Keeping `mdlast` fresh makes it safer to SHOW, not safe to trade on.
    `ltp`/`bid`/`ask` stay 0 so the engine's stale-feed guard still holds."""
    import inspect

    from app.services import market_data_service as mds

    src = inspect.getsource(mds._attach_last_quote)
    for field in ("ltp", "bid", "ask"):
        assert f'out["{field}"] =' not in src, field
