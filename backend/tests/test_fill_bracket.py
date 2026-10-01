"""A stop set on one fill belongs to that fill alone.

Reported with a screenshot: two BTCUSD entries on the Active tab, both BUY
10, one at 83,810.01 and one at 83,815.17. The trader set SL 83,000 / TP
85,900 on ONE of them and both rows came back carrying it.

    BUY Qty 10   BTCUSD   83,810.01 → 83,770.46   SL 83000.00 / TP 85900.00
    BUY Qty 10   BTCUSD   83,815.17 → 83,770.46   SL 83000.00 / TP 85900.00

The Active tab is a per-fill view — its own entry price, its own P&L, its own
Exit — but its SL/TP buttons wrote to the parent Position, and every row read
its bracket back from there. One leg, displayed N times, closing everything
at once.

Operator: "ek me SL lagaya hai, dono me lag raha hai — Active me sahi se
karo."

Three things have to hold together, and the middle one is the dangerous one:

  1. the leg is STORED on the fill
  2. the enforcer FIRES it against that fill's own open quantity — a leg that
     only displays per fill but closes the whole position is worse than no
     leg at all, because the trader believes one entry is protected and
     loses the others with it
  3. a position and its fills NEVER both carry a leg, or one move closes the
     position twice
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.api.v1.user import positions as api
from app.models._base import OrderAction
from app.models.trade import Trade
from app.services import risk_enforcer
from app.services.position_service import open_fill_leftovers


# ── 1. the leg is stored on the fill ──────────────────────────────────
def test_the_fill_carries_its_own_bracket():
    for field in ("stop_loss", "target", "bracket_ref_high", "bracket_ref_low"):
        assert field in Trade.model_fields, field


def test_the_active_endpoint_writes_to_the_fill_not_the_position():
    src = inspect.getsource(api.update_active_trade_sl_tp)
    assert "target_doc = t if t is not None else p" in src
    assert "target_doc.stop_loss" in src and "target_doc.target" in src
    # The synthetic `pos-` row has no fill behind it and must still work.
    assert "pos-" in src


def test_each_fill_gets_its_own_watermark():
    """Two legs set minutes apart have different ideas of where the day had
    been, so one watermark for both would fire the younger leg on an extreme
    that predates it."""
    src = inspect.getsource(api.update_active_trade_sl_tp)
    assert "_stamp_bracket_ref(target_doc)" in src
    assert "bracket_ref_high" in inspect.getsource(risk_enforcer._fire_fill_brackets)


# ── 2. the enforcer fires it, and only for that fill ──────────────────
def test_the_enforcer_has_a_per_fill_pass():
    src = inspect.getsource(risk_enforcer)
    assert "_fire_fill_brackets" in src


def test_the_per_fill_pass_runs_before_the_position_level_one():
    """And short-circuits it. Running both would close the position twice for
    a single move."""
    src = inspect.getsource(risk_enforcer._enforce_for_user)
    assert "_fire_fill_brackets" in src
    assert src.index("_fire_fill_brackets") < src.index("bracket_sl_long")
    gate = src[src.index("_fire_fill_brackets") :]
    assert "continue" in gate[: gate.index("hit_reason")]


def test_the_close_is_scoped_to_the_fills_own_quantity():
    src = inspect.getsource(risk_enforcer._fire_fill_brackets)
    assert "qty=left" in src
    # A fill already consumed by a closing leg has nothing left to protect.
    assert "if left <= 0" in src


def test_squareoff_can_close_part_of_a_position():
    sig = inspect.signature(risk_enforcer._squareoff_position)
    assert "qty" in sig.parameters
    assert sig.parameters["qty"].default is None


def test_a_partial_close_never_exceeds_the_position():
    """A stale leftover must not turn a close into an opposite-side OPEN."""
    src = inspect.getsource(risk_enforcer._squareoff_position)
    assert "min(float(qty), abs(p.quantity))" in src


def test_the_fire_is_claimed_atomically_like_the_position_one():
    """The loop runs in every worker. Without the claim, two of them fire the
    same leg and two opposite-side orders land for one close."""
    src = inspect.getsource(risk_enforcer._fire_fill_brackets)
    assert 'leg_field: {"$ne": None}' in src
    assert "modified_count" in src
    # And the leg goes back if the close itself fails, or it is lost.
    assert "restore" in src


# ── 3. a position and its fills never both carry a leg ────────────────
def test_setting_a_fill_leg_takes_the_position_leg_down():
    src = inspect.getsource(api.update_active_trade_sl_tp)
    assert "_push_position_legs_down_to_fills" in src


def test_the_other_fills_inherit_what_they_were_showing():
    """They were visibly covered by the position's leg a second ago; dropping
    it silently would leave them unprotected without anyone being told."""
    src = inspect.getsource(api._push_position_legs_down_to_fills)
    assert "f.stop_loss is None and f.target is None" in src
    assert "p.stop_loss = None" in src and "p.target = None" in src


def test_setting_a_position_leg_takes_the_fill_legs_off():
    src = inspect.getsource(api.update_sl_tp)
    assert "_clear_fill_legs" in src


def test_the_listing_prefers_the_fills_own_leg():
    src = inspect.getsource(api.list_active_trades)
    assert 'str(t.stop_loss)' in src and 'str(t.target)' in src
    assert 'getattr(t, "stop_loss", None) is not None' in src


# ── the FIFO the whole thing rests on ─────────────────────────────────
def _fill(tid: str, side: str, qty: float, at: int):
    from datetime import datetime, timezone

    return SimpleNamespace(
        id=tid,
        action=OrderAction.BUY if side == "BUY" else OrderAction.SELL,
        quantity=qty,
        product_type=SimpleNamespace(value="NRML"),
        instrument=SimpleNamespace(token="t1"),
        executed_at=datetime(2026, 10, 1, 9, at, tzinfo=timezone.utc),
        created_at=None,
    )


def _pos(qty: float):
    return SimpleNamespace(
        quantity=qty,
        product_type=SimpleNamespace(value="NRML"),
        instrument=SimpleNamespace(token="t1"),
        opened_at=None,
    )


def test_two_untouched_fills_each_keep_their_whole_size():
    """The screenshot's case: two BUY 10s, nothing closed."""
    out = open_fill_leftovers(_pos(20), [_fill("a", "BUY", 10, 1), _fill("b", "BUY", 10, 2)])
    assert out == {"a": 10, "b": 10}


def test_a_closing_leg_eats_the_oldest_fill_first():
    out = open_fill_leftovers(
        _pos(12),
        [_fill("a", "BUY", 10, 1), _fill("b", "BUY", 10, 2), _fill("c", "SELL", 8, 3)],
    )
    assert out == {"a": 2, "b": 10}


def test_a_fully_consumed_fill_drops_out():
    out = open_fill_leftovers(
        _pos(10),
        [_fill("a", "BUY", 10, 1), _fill("b", "BUY", 10, 2), _fill("c", "SELL", 10, 3)],
    )
    assert out == {"b": 10}


def test_a_short_position_consumes_its_sells():
    out = open_fill_leftovers(
        _pos(-12),
        [_fill("a", "SELL", 10, 1), _fill("b", "SELL", 10, 2), _fill("c", "BUY", 8, 3)],
    )
    assert out == {"a": 2, "b": 10}


def test_it_falls_back_when_scoping_comes_up_short():
    """An admin edit or a reopen can leave `opened_at` ahead of the fills.
    Returning less than the position holds would leave part of it with no row
    to close it from, so the newest same-side fills are claimed instead."""
    from datetime import datetime, timezone

    p = _pos(15)
    p.opened_at = datetime(2026, 10, 1, 23, 0, tzinfo=timezone.utc)  # after every fill
    out = open_fill_leftovers(p, [_fill("a", "BUY", 10, 1), _fill("b", "BUY", 10, 2)])
    assert sum(out.values()) == 15
    assert out["b"] == 10  # newest first


def test_a_flat_position_has_no_open_fills():
    assert open_fill_leftovers(_pos(0), [_fill("a", "BUY", 10, 1)]) == {}
