"""Partial carry-forward at market close — the sizing has to be self-consistent.

The operator's rule: at close, the carry budget is the free balance PLUS the
position's P&L, and that budget times the overnight leverage is what may carry.
The rest is squared.

    wallet 1,00,000 · intraday 100x · carry 40x · P&L +25,000
    budget 1,25,000 -> 1,25,000 x 40 = 50,00,000 may carry, 50,00,000 squared

    carriable_qty = (available + freed intraday margin + float P&L + credit)
                    × overnight_leverage ÷ LTP

The historical trap: squaring the excess only turns the SQUARED part's profit
into cash; the CARRIED part's profit is still floating. Back when block_margin
checked cash alone, a carry sized against the overnight margin could not be
re-locked — it was short by exactly the carried part's floating profit, every
time the position was in profit, and the remainder was left in MIS overnight.

The segment wallet now runs the free-margin (dabba/CFD) model: block_margin
credits the live floating P&L as buying power (cash_needed = margin − float_pnl,
see `segment_wallet_service.block_margin`). So the carried part's own float
backs its re-lock — the denominator no longer needs the conservative
"+ floating_profit" haircut, and the carriable qty follows the operator's
formula exactly (LTP-based, P&L symmetric). These tests model that contract.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.services import position_service

ZERO = D(0)


def _plan(wallet: D, intraday_x: D, carry_x: D, pnl: D, credit: D = ZERO) -> dict:
    """Mirror of `convert_intraday_to_carry`'s partial-carry arithmetic under the
    free-margin (dabba/CFD) model: the denominator is the overnight margin ALONE
    (no profit haircut), and the re-lock is backed by cash PLUS the carried
    part's live floating P&L — exactly what `segment_wallet_service.block_margin`
    credits."""
    notional = wallet * intraday_x
    old_margin = notional / intraday_x          # locked at entry
    available = wallet - old_margin             # block_margin moved it out
    new_margin = notional / carry_x             # full overnight requirement

    funds = available + old_margin + pnl + credit
    denom = new_margin                          # free-margin: no +profit haircut
    carried = min(funds / denom, D(1)) if funds > ZERO and denom > ZERO else ZERO
    squared = D(1) - carried

    # after the square: this position's margin frees pro-rata and the squared
    # part's P&L is realised into the wallet
    avail_after = available + old_margin * squared + pnl * squared
    # free-margin re-lock: block_margin credits the CARRIED part's floating P&L
    # as buying power, so it counts toward what the wallet can back.
    carried_float = pnl * carried
    relock_needs = (new_margin - old_margin) * carried
    relock_has = avail_after + credit + carried_float
    return {
        "notional": notional,
        "carried_notional": notional * carried,
        "squared_notional": notional * squared,
        "relock_needs": relock_needs,
        "relock_has": relock_has,
        "relock_ok": relock_has >= relock_needs,
    }


def _old_plan(wallet: D, intraday_x: D, carry_x: D, pnl: D) -> dict:
    """The formula as it shipped — divides by `new_margin` alone."""
    notional = wallet * intraday_x
    old_margin = notional / intraday_x
    available = wallet - old_margin
    new_margin = notional / carry_x
    funds = available + old_margin + pnl
    carried = min(funds / new_margin, D(1)) if funds > ZERO else ZERO
    squared = D(1) - carried
    avail_after = available + old_margin * squared + pnl * squared
    return {
        "relock_needs": (new_margin - old_margin) * carried,
        "relock_has": avail_after,
        "relock_ok": avail_after >= (new_margin - old_margin) * carried,
    }


# -- the bug this fixes -------------------------------------------------
def test_the_old_formula_could_not_relock_a_winning_position():
    """The operator's own example. This is what was leaving positions in MIS."""
    old = _old_plan(D(100000), D(100), D(40), D(25000))
    assert not old["relock_ok"]
    # short by exactly the profit on the carried half
    assert old["relock_needs"] - old["relock_has"] == D(12500)


@pytest.mark.parametrize("pnl", [D(1), D(2033), D(25000), D(500000)])
def test_a_winning_position_can_now_be_relocked(pnl):
    """Any profit at all used to break it, so check across the range."""
    assert _plan(D(100000), D(100), D(40), pnl)["relock_ok"]


@pytest.mark.parametrize("pnl", [D(-1), D(-2255), D(-25000)])
def test_a_losing_position_still_works(pnl):
    """The loss path was never broken and is deliberately left alone."""
    assert _plan(D(100000), D(100), D(40), pnl)["relock_ok"]


def test_a_flat_position_still_works():
    assert _plan(D(100000), D(100), D(40), ZERO)["relock_ok"]


# -- the numbers themselves --------------------------------------------
def test_profit_still_buys_more_carry_than_ignoring_it():
    """The operator's point is that P&L counts. It must move the number."""
    with_pnl = _plan(D(100000), D(100), D(40), D(25000))["carried_notional"]
    without = _plan(D(100000), D(100), D(40), ZERO)["carried_notional"]
    assert with_pnl > without == D(4000000)


def test_a_loss_carries_less_than_flat():
    """P&L is symmetric now: a floating loss shrinks the carry budget."""
    with_loss = _plan(D(100000), D(100), D(40), D(-25000))["carried_notional"]
    flat = _plan(D(100000), D(100), D(40), ZERO)["carried_notional"]
    assert with_loss < flat == D(4000000)


def test_the_carried_part_is_exactly_what_the_wallet_can_back():
    """Sized to the boundary — not a safety haircut, not an overshoot.

    Compared to the paisa: 1/2.2 is a repeating decimal, so the two sides can
    differ in the 20th place. The real path floors to whole lots on top of
    this, which only ever lands under.
    """
    p = _plan(D(100000), D(100), D(40), D(25000))
    assert abs(p["relock_needs"] - p["relock_has"]) < D("0.01")
    assert p["carried_notional"] + p["squared_notional"] == p["notional"]


def test_a_loss_deep_enough_carries_nothing():
    """Budget gone → the whole position squares, not a negative carry."""
    p = _plan(D(100000), D(100), D(40), D(-200000))
    assert p["carried_notional"] == ZERO
    assert p["squared_notional"] == p["notional"]


def test_nothing_is_squared_when_the_wallet_covers_it_all():
    """A 40x carry on a 40x position needs no square-off at all."""
    p = _plan(D(100000), D(40), D(40), ZERO)
    assert p["squared_notional"] == ZERO
    assert p["carried_notional"] == p["notional"]


# -- wiring -------------------------------------------------------------
def test_the_service_uses_the_corrected_denominator():
    src = inspect.getsource(position_service.convert_intraday_to_carry)
    assert "_carry_denom" in src
    assert "raw_lots = (cur_qty_abs * funds / _carry_denom)" in src


def test_the_denominator_is_ltp_based_with_no_profit_haircut():
    """Free-margin model: size against the overnight margin at the LIVE close
    price (LTP), and DON'T add floating profit to the denominator — block_margin
    already credits the carried float as buying power."""
    src = inspect.getsource(position_service.convert_intraday_to_carry)
    # carriable qty is measured against the LTP notional, not the entry avg
    assert "_carry_denom = (_ltp_now * cur_qty_abs)" in src
    # the old conservative "+ floating_profit" haircut is gone
    assert "unreal if unreal > 0 else to_decimal(0)" not in src


def test_a_skipped_position_says_why():
    """`skipped` used to be silent, so a stuck position could not be explained."""
    src = inspect.getsource(position_service.convert_intraday_to_carry)
    assert "carry_partial_relock_failed" in src
    assert "carry_partial_failed" in src
