"""A stop-loss could rest at a price the contract does not trade at.

Reported on CRUDEOIL26OCTFUT: "ye tick 1 ka hai, SL/TP .5 me bhi lag ja rahi
hai". MCX GOLD / SILVER / CRUDEOIL / COPPER futures trade in whole rupees.

Typed ENTRY prices were already snapped — `order_service` rounds `price` and
`trigger_price` onto the tick. The three places a bracket leg is written were
not: the two SL/TP handlers on a position and the legs carried in with a new
order. So a limit could not be typed off-tick but a stop could.

The stored tick is not usable for this. An `InstrumentRef` embedded on a
Position is a SNAPSHOT taken when it opened, so a position from before the MCX
correction still carries 0.05 — `effective_tick` reads the override instead,
which is the same one the catalog and the order panel already go through.

Snapping happens BEFORE the direction guard and the range checks, so every one
of them judges the number that will actually be stored. Snapping afterwards
could push a leg onto the wrong side of the price and hand a "valid" level to
the enforcer that fires instantly.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from app.api.v1.user import positions as pos
from app.services import instrument_service as isvc
from app.services import order_service


class _Ref:
    """What a Position actually carries: a ref, not the full row — and with a
    STALE tick, which is the case that was going wrong."""

    symbol = "CRUDEOIL26OCTFUT"
    segment = "MCX_FUTURE"
    tick_size = "0.05"


class _Eq:
    symbol = "SBIN"
    segment = "NSE_EQUITY"
    tick_size = "0.05"


def test_a_whole_rupee_future_ignores_its_stale_stored_tick():
    assert isvc.effective_tick(_Ref()) == Decimal("1.0")


def test_the_reported_case_snaps_to_a_rupee():
    assert isvc.snap_price(_Ref(), "8940.5") == Decimal("8940")
    assert isvc.snap_price(_Ref(), "8941.4") == Decimal("8941")
    assert isvc.snap_price(_Ref(), "8941.6") == Decimal("8942")


def test_everything_else_keeps_its_own_tick():
    # A 1-rupee tick on equity would be a huge step; only the MCX futures
    # roots are overridden.
    assert isvc.effective_tick(_Eq()) == Decimal("0.05")
    assert isvc.snap_price(_Eq(), "249.67") == Decimal("249.65")


def test_clearing_a_leg_still_clears_it():
    # Empty / zero must pass through as None, or "leave a box empty to clear
    # that leg" would stop working.
    for blank in (None, "", 0, "0"):
        assert isvc.snap_price(_Ref(), blank) is None


def test_a_ref_with_no_instrument_type_is_still_recognised_as_a_future():
    # An InstrumentRef has no `instrument_type`; the segment and the symbol
    # both say FUT, and the override only applies to futures.
    class _NoSeg:
        symbol = "CRUDEOIL26OCTFUT"
        segment = ""
        tick_size = "0.05"

    assert isvc.effective_tick(_NoSeg()) == Decimal("1.0")


def test_a_copper_option_is_left_alone():
    # Its premium is around 13.99 — a 1-rupee tick would be a ~7% step.
    class _Opt:
        symbol = "COPPER26SEP1400CE"
        segment = "MCX_OPTION_BUY"
        tick_size = "0.05"

    assert isvc.effective_tick(_Opt()) == Decimal("0.05")


# ── the three write sites ───────────────────────────────────────────────────

def test_both_sl_tp_handlers_snap():
    src = inspect.getsource(pos)
    assert src.count("instrument_service.snap_price(p.instrument, payload[_leg])") == 2


def test_snapping_runs_before_the_checks_that_judge_the_level():
    src = inspect.getsource(pos)
    assert src.index("snap_price(p.instrument") < src.index("sl_val = _to_float(")
    assert src.index("_sl_in = payload.get(") > src.rindex("snap_price(p.instrument")


def test_a_new_order_s_bracket_legs_snap_too():
    src = inspect.getsource(order_service.place_order)
    assert "bracket_sl = instrument_service.snap_price(instrument, raw_sl)" in src
    assert "bracket_tp = instrument_service.snap_price(instrument, raw_tp)" in src


def test_fill_prices_are_still_left_alone():
    # Rounding a fill would move realised P&L away from the market by up to
    # half a tick on every trade.
    assert "ENTRY PRICES ONLY" in inspect.getsource(order_service.place_order)
