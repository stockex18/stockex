"""The three index chains everyone opens are held, not fetched per viewer.

NIFTY, BANKNIFTY and SENSEX were subscribed the moment somebody looked at
them — a fresh subscription per strike, per viewer, competing for the same
1,500-slot list the LRU then evicted from. The second viewer paid what the
first did, and the chain rendered blank while Kite caught up.

Nothing about those strikes is per-user and they are wanted every session, so
they are warmed once and held. The risks worth pinning: warming the WRONG
ladder (the money moves), and warming so many that this recreates the very
list-flooding it is meant to end.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import core_feed_warm as warm


def test_only_the_three_the_picker_offers():
    """The chain UI shows exactly these. Warming a fourth would hold strikes
    nobody can reach."""
    assert warm.CORE_UNDERLYINGS == ("NIFTY", "BANKNIFTY", "SENSEX")


def test_the_picker_and_the_warm_set_agree():
    import io

    ui = io.open(
        r"D:\stockex_new\frontend-user\components\trading\MobileOptionChain.tsx",
        encoding="utf-8", errors="ignore",
    ).read()
    block = ui[ui.index("const UNDERLYINGS"): ui.index("const UNDERLYINGS") + 700]
    for root in warm.CORE_UNDERLYINGS:
        assert f'symbol: "{root}"' in block, root
    for gone in ("FINNIFTY", "MIDCPNIFTY", "BANKEX"):
        assert gone not in block, f"{gone} still in the picker with no warm feed behind it"


def test_the_backend_default_agrees_too():
    from app.api.v1.user import option_chain as oc

    assert {u["symbol"] for u in oc._DEFAULT_UNDERLYINGS} == set(warm.CORE_UNDERLYINGS)


# ── the ladder ────────────────────────────────────────────────────────
def test_six_each_side_is_thirteen_strikes():
    """ATM plus six above and six below — not six in total."""
    assert warm.DEFAULT_WARM_STRIKES == 6
    src = inspect.getsource(warm.collect_core_tokens)
    assert "strikes * 2 + 1" in src


def test_it_ranks_by_distance_from_the_money():
    """A ladder sliced by index rather than by distance warms whatever happens
    to sort first — usually the deepest, least-traded strikes."""
    src = inspect.getsource(warm.collect_core_tokens)
    assert "key=lambda k: abs(k - spot)" in src


def test_it_keeps_both_sides_of_each_strike():
    """Selecting rows rather than STRIKES lets a call-heavy ladder crowd out
    the puts at the same price."""
    src = inspect.getsource(warm.collect_core_tokens)
    assert "by_strike" in src
    assert "for r in by_strike[k]:" in src


def test_it_only_takes_the_nearest_live_expiry():
    src = inspect.getsource(warm.collect_core_tokens)
    assert '"expiry": {"$gte": now}' in src
    assert 'sort("+expiry")' in src


def test_an_unreadable_spot_warms_nothing_for_that_chain():
    """No spot means no ATM, and a guessed ATM is a guessed ladder."""
    src = inspect.getsource(warm.collect_core_tokens)
    assert "if spot <= 0:" in src and "continue" in src


def test_one_bad_chain_does_not_stop_the_others():
    src = inspect.getsource(warm.collect_core_tokens)
    assert "core_warm_root_failed" in src


# ── the flood guard ───────────────────────────────────────────────────
def test_an_unexpected_ladder_size_warms_nothing():
    """3 underlyings x 13 strikes x 2 sides is ~78. Hundreds means a bad read,
    and quietly subscribing them recreates the flood this exists to end."""
    assert warm._MAX_WARM_TOKENS == 200
    src = inspect.getsource(warm.collect_core_tokens)
    assert "if len(out) > _MAX_WARM_TOKENS:" in src
    assert "return {}" in src


@pytest.mark.asyncio
async def test_nothing_to_warm_is_not_an_error(monkeypatch):
    async def _none(strikes=6):
        return {}

    monkeypatch.setattr(warm, "collect_core_tokens", _none)
    assert await warm.warm_core_feed_once() == 0


# ── wiring ────────────────────────────────────────────────────────────
def test_it_also_enters_the_set_tick_loop_mirrors_from():
    """Subscribing on Kite alone leaves the chain invisible to every
    non-leader worker — `_subscribed` is what puts it in `mdlive`."""
    src = inspect.getsource(warm.warm_core_feed_once)
    assert "mds.subscribe(" in src


def test_it_passes_symbols_with_the_tokens():
    """A symbol-less subscribe is what filled the list with bare numbers and
    stopped FULL mode being re-asserted."""
    src = inspect.getsource(warm.warm_core_feed_once)
    assert "subscribe_tokens_on_demand(list(tokens), tokens)" in src


def test_it_reruns_because_the_money_moves():
    """A ladder warmed at 09:15 is the wrong one by afternoon if the index has
    travelled."""
    src = inspect.getsource(warm.core_feed_warm_loop)
    assert "await asyncio.sleep(interval_sec)" in src


def test_the_loop_runs_where_the_feed_is():
    from app import main

    src = inspect.getsource(main)
    assert "core_feed_warm" in src
    assert "core_feed_warm_loop, interval_sec=300.0" in src
