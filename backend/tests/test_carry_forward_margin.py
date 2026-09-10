"""The overnight carry has to cost what the operator says it costs.

Three separate reports, one root cause: the overnight-margin formula existed in
THREE places and only the display copy had been kept current.

    api/v1/user/positions.py     display        correct (fixed earlier)
    _fifo_carry_plan             sizes the trim  no strike_pct branch
    convert_intraday_to_carry    re-locks money  no strike_pct branch, and
                                                 priced at the ENTRY price

A written option therefore carried on its PREMIUM instead of its strike:

    COPPER26SEP1400CE  qty 1430  strike 1400  premium 13.99
      planner saw    1430 x 13.99         =   20,005.70
      really needs   1430 x 1400 x 0.08   = 1,60,160.00

Eight times light, per written leg, so the portfolio `need` came out far under
the truth and the plan squared far too little. Operator's own arithmetic on the
live book: a 21.2L requirement against a 10.5L wallet should have squared
SILVER whole and ~79 of 100 GOLD. It squared SILVER and 46 GOLD, and carried
the rest uncovered.

The numbers below are that book, taken off the operator's screenshots.
"""

from __future__ import annotations

import inspect

from app.services import position_service as ps
from app.utils.decimal_utils import to_decimal


def _times(lev: float) -> dict:
    """What the resolver hands back for Times mode."""
    return {
        "margin_calc_mode": "times",
        "overnight_margin_percentage": 100.0,
        "overnight_leverage": lev,
    }


def _strike_pct(rate: float) -> dict:
    """What the resolver hands back for strike_pct: the percent/leverage pair
    is 100 / 1x, which is exactly why a missing branch collapses to the
    premium instead of failing loudly."""
    return {
        "margin_calc_mode": "strike_pct",
        "overnight_margin_percentage": 100.0,
        "overnight_leverage": 1.0,
        "overnight_strike_margin_rate": rate,
    }


def _m(s, qty, mark, *, strike=0, lot=1, usd=False):
    return ps.overnight_margin(
        s,
        qty=to_decimal(qty),
        mark=to_decimal(mark),
        lot_size=lot,
        strike=to_decimal(strike),
        is_usd=usd,
    )


# ── the operator's book, leg by leg ───────────────────────────────────
def test_futures_carry_on_the_current_price():
    """SILVER26SEPFUT 63.75 @ 231001, overnight 25x. Priced at the market, not
    at the 235380 it was filled at."""
    assert _m(_times(25), 63.75, 231001) == to_decimal("589052.55")


def test_the_other_future():
    """GOLD26OCTFUT 100 @ 152818, overnight 25x."""
    assert _m(_times(25), 100, 152818) == to_decimal("611272.00")


def test_a_written_call_sits_on_the_strike():
    """COPPER26SEP1400CE 1430, strike 1400, overnight rate 0.08."""
    assert _m(_strike_pct(0.08), 1430, 13.99, strike=1400) == to_decimal("160160.00")


def test_the_other_written_call():
    """CRUDEOIL26SEP8650CE 231.5, strike 8650."""
    assert _m(_strike_pct(0.08), 231.5, 246.40, strike=8650) == to_decimal("160198.00")


def test_a_bought_option_is_qty_times_price_over_the_leverage():
    """COPPER26SEP1400PE 17500 @ 34.13, overnight 2x. Operator, exactly:
    "option buy should multiply Qty with BID (LTP) then divided by 2, or
    whatever the leverage"."""
    assert _m(_times(2), 17500, 34.13) == to_decimal("298637.50")


def test_the_other_bought_option():
    """CRUDEOIL26SEP8650PE 1657 @ 310."""
    assert _m(_times(2), 1657, 310) == to_decimal("256835.00")


def test_the_whole_book_adds_up_to_what_the_operator_totalled():
    """All six legs. This is the `need` the FIFO planner divides the wallet
    against, so if it drifts the trim size drifts with it."""
    need = (
        _m(_times(25), 63.75, 231001)
        + _m(_times(25), 100, 152818)
        + _m(_strike_pct(0.08), 1430, 13.99, strike=1400)
        + _m(_strike_pct(0.08), 231.5, 246.40, strike=8650)
        + _m(_times(2), 17500, 34.13)
        + _m(_times(2), 1657, 310)
    )
    assert need == to_decimal("2076155.05")


# ── the bug itself ────────────────────────────────────────────────────
def test_a_written_option_is_never_margined_on_its_premium():
    """The old fall-through. 1430 x 13.99 = 20,005.70 — eight times light, and
    the whole reason too little was squared."""
    got = _m(_strike_pct(0.08), 1430, 13.99, strike=1400)
    assert got != to_decimal("20005.70")
    assert got > to_decimal("20005.70") * 7


def test_a_missing_strike_falls_through_rather_than_squaring_somebody_off():
    """A strike of 0 cannot compute strike margin. Falling back to the generic
    path under-margins the leg — but force-closing a live position over a gap
    in the instrument catalog is the worse failure. It is logged instead."""
    assert _m(_strike_pct(0.08), 1430, 13.99, strike=0) == to_decimal("20005.70")
    assert "carry_strike_margin_unresolved" in inspect.getsource(ps.overnight_margin)


def test_fixed_per_lot_still_wins_and_stays_in_rupees():
    """An admin-typed rupees-per-lot figure is already INR, so the USD
    conversion must not touch it."""
    s = {"margin_calc_mode": "fixed", "overnight_fixed_margin_per_lot": 15000}
    assert _m(s, 300, 250, lot=100, usd=True) == to_decimal("45000.00")


# ── one formula, not three ────────────────────────────────────────────
def test_the_planner_and_the_executor_share_it():
    """They used to compute this separately: the planner decided how much to
    square using the live mark, the executor re-locked using the entry price.
    A plan and an execution that disagree is how a wallet ends the night above
    the exposure the plan sized it for."""
    assert "overnight_margin(" in inspect.getsource(ps._fifo_carry_plan)
    assert "overnight_margin(" in inspect.getsource(ps.convert_intraday_to_carry)


def test_the_executor_prices_the_relock_at_the_exit_side_of_the_book():
    """Operator rule 2: "margin to be calculated, qty multiply to current
    bid/ask". Not the entry price it used to read, and not the LTP either -
    the side this position would actually exit on."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert "_mark = await _exit_price(pos.instrument.token, _exit_action(pos), _ltp_now)" in src
    assert "mark=_mark" in src
    assert "notional = cur_avg * cur_qty_abs" not in src


def test_the_planner_prices_it_the_same_way():
    """If the plan and the re-lock measure at different prices the trim is
    sized against a number the money never matches."""
    src = inspect.getsource(ps._fifo_carry_plan)
    assert "_mark = await _exit_price(pos.instrument.token, _exit_action(pos), _ltp)" in src
    assert "mark=_mark" in src


def test_a_long_exits_at_the_bid_and_a_short_at_the_ask():
    """`_exit_action` is what routes each position to its side of the book, and
    it is the same rule `refresh_unrealized_pnl` already marks P&L with."""
    from types import SimpleNamespace

    from app.models._base import OrderAction

    assert ps._exit_action(SimpleNamespace(quantity=100)) == OrderAction.SELL
    assert ps._exit_action(SimpleNamespace(quantity=-100)) == OrderAction.BUY


# -- rule 3: the wallet balance, AS THE OPERATOR READS IT ---------------
#
# This section pinned the wrong thing for one day and it cost real positions.
#
# "cf should be only according to wallet balance" was read as the STORED
# `available_balance` field, so floating P&L came out of the carry budget. But
# the balance the operator means is the one on his screen, and that figure has
# floating P&L in it already - as does every other consumer on the platform:
#
#     order_validator   available += segment_float_pnl(...)
#     block_margin      cash_needed = margin - float_pnl
#     AVAILABLE tile    avail + credit_limit + float_pnl
#
# The planner was left alone in disagreeing with all of them and over-squared
# by exactly the floating profit. Live, 2026-09-07 15:41: screen balance
# 8,05,002.58, stored cash 4,96,768.34, and the sweep closed BANKNIFTY26SEPFUT
# whole and cut NIFTY26SEPFUT 313.95 -> 63 while leaving 3,02,393 unused.
#
#     admin: "my wallet balance is 805000 at the time of closing, but the
#             software has carry forward for 5 lac only, it has not added
#             pnl of 3 lac"
def test_the_carry_budget_matches_the_balance_on_the_screen():
    """Cash plus locked margin plus floating P&L. Credit limit stays out -
    that is a separate facility and has never backed an overnight carry."""
    src = inspect.getsource(ps._fifo_carry_plan)
    assert "available = to_decimal(wallet.available_balance) + to_decimal(" in src
    assert "wallet.used_margin" in src
    assert "available += await _segment_float(user_id, _kind)" in src
    assert "wallet.credit_limit" not in src


def test_the_fallback_says_the_same_thing():
    """A planner failure must not silently change how much gets squared, so it
    counts the same three things and still leaves credit out."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert src.count("await _segment_float(") == 2
    assert "funds = (" in src and "+ old_margin" in src
    assert "wallet.credit_limit" not in src


def test_the_float_comes_from_the_platforms_own_helper():
    """Not a private re-implementation. If the carry computes float P&L its own
    way it will drift from the validator and the tile, which is the whole
    failure this is fixing."""
    src = inspect.getsource(ps._segment_float)
    assert "segment_wallet_service.segment_float_pnl" in src


def test_a_float_that_will_not_resolve_is_zero_not_an_error():
    """It must never become a reason to square somebody off."""
    src = inspect.getsource(ps._segment_float)
    assert "except Exception" in src
    assert "return ZERO" in src
    assert "carry_float_pnl_failed" in src


def test_the_main_wallet_has_no_segment_float():
    src = inspect.getsource(ps._segment_float)
    assert "wallet_kinds.is_segment_kind(kind)" in src


def test_floating_pnl_is_gone_from_the_carry_entirely():
    """Not merely unused - removed. A leftover `unreal` in scope is an
    invitation to wire it back in without meaning to. Matching the assignment
    at its own indentation, so the history of it in the comments does not
    count as the thing itself."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert "\n        unreal = " not in src
    assert "\n        _sign = " not in src


def test_the_fallback_sizing_cannot_drift_from_the_plan_again():
    """The partial branch had its OWN denominator — a fourth copy, also
    missing strike_pct. It is now the same figure the affordability gate
    used."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert "_carry_denom = new_margin" in src


def test_the_strike_is_looked_up_once_for_the_whole_sweep():
    """`InstrumentRef` carries no strike, and a query per position on a
    close-time sweep of every open position is a query per position."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert "_strike_by_token = await _strikes_for(rows)" in src
    assert "_fifo_carry_plan(rows, _strike_by_token)" in src


async def test_the_strike_lookup_falls_back_to_the_symbol():
    """Some option docs carry a NULL strike; the validator already parses the
    monthly symbol for exactly this reason."""
    from app.services.order_validator import _strike_from_symbol

    assert _strike_from_symbol("COPPER26SEP1400CE") == to_decimal(1400)
    assert _strike_from_symbol("CRUDEOIL26SEP8650PE") == to_decimal(8650)
    assert "_strike_from_symbol" in inspect.getsource(ps._strikes_for)


# ── the square-off fills on the side it exits on ──────────────────────
async def test_a_long_exits_into_the_bid_and_a_short_lifts_the_ask(monkeypatch):
    """Operator: "Gold should square off @ 152666 not 152815" — the rollover
    was forcing the LTP, a price on neither side of the book. GOLD is SHORT, so
    it exits by BUYING at the ask; a long exits at the bid."""
    from app.models._base import OrderAction
    from app.services import market_data_service as mds

    async def fake(_token):
        return {"bid": 152666.0, "ask": 152818.0, "ltp": 152815.0}

    monkeypatch.setattr(mds, "get_quote", fake)
    buy = await ps._exit_price("x", OrderAction.BUY, to_decimal(152815))
    sell = await ps._exit_price("x", OrderAction.SELL, to_decimal(152815))
    assert buy == to_decimal("152818.0")
    assert sell == to_decimal("152666.0")


async def test_a_crossed_or_missing_book_keeps_the_mark(monkeypatch):
    """An inverted quote points BOTH sides the wrong way — the exit would take
    the better price on either side. And the carry runs at the close, when
    there may be no book at all; without a forced price the engine's zero-price
    guard leaves the position stuck MIS overnight."""
    from app.models._base import OrderAction
    from app.services import market_data_service as mds

    async def crossed(_token):
        return {"bid": 1352.0, "ask": 1273.40}

    async def empty(_token):
        return {"bid": 0, "ask": 0}

    for q in (crossed, empty):
        monkeypatch.setattr(mds, "get_quote", q)
        assert await ps._exit_price("x", OrderAction.BUY, to_decimal(99)) == to_decimal(99)


def test_the_squareoff_still_forces_a_price():
    """It has to. Dropping `force_fill_price` re-opens the STALE_FEED wedge
    that left positions stuck MIS overnight."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert '"force_fill_price": float(_exit_px) if _exit_px > 0 else None' in src


# ── the FIFO rule the operator spelled out ────────────────────────────
def test_oldest_first_and_only_the_boundary_is_partial():
    """Operator: "square all silver, then square partial gold ... rest all
    position will be carry forward"."""
    src = inspect.getsource(ps._fifo_carry_plan)
    assert 'recs.sort(key=lambda r: r["opened_at"]' in src
    # Sized on the NET a square frees — its overnight margin less the
    # brokerage that square books out of the same wallet.
    assert "frac_carry = (net - gap) / net" in src


def test_the_boundary_fraction_matches_the_operators_arithmetic():
    """Wallet 10,52,825 against a 21.23L need leaves 10,70,251 to raise.
    SILVER releases 5,89,052 whole; GOLD covers the remaining 4,81,199 of its
    6,11,272 — so 21.28% of it carries."""
    gap = to_decimal("481199")
    m = to_decimal("611272")
    frac = (m - gap) / m
    assert round(float(frac) * 100, 2) == 21.28
