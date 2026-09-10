"""A position that could not fund its carry was left in MIS overnight.

Live, 2026-09-09 MCX, one user. The planner squared five CRUDEOIL option legs
whole and partial-trimmed a sixth (200 -> 109), then carried the rest. The last
flip could not be funded:

    18:01:02  carry_convert_failed        LEAD26SEPFUT
              have 17,785.29 (+float 21,840.00)   need 50,043.75
    18:01:03  carry_convert_retry_failed  need=50043.750
              have   -553.86 (+float 21,840.00)   need 50,043.75

Both passes failed, so the leg was left in MIS — which is neither carried nor
closed. It stayed open all night on 50,298.75, its INTRADAY margin at 100x,
when the carry needed 1,00,342.50 at 50x. Half the margin, for a whole night.

Two defects, fixed together:

1. THE PLAN spent money it was about to pay away. `released` counted the
   overnight margin a square frees but not the brokerage that square books out
   of the same wallet — so a plan could land exactly on the line and then be
   short by the charges. The five trims that night booked 84.51.

2. THE SWEEP trusted the plan over the wallet. When the flip still failed, the
   leg was left as it was. The wallet is the authority at rollover: a leg that
   cannot fund its carry margin must be squared.

(2) is what makes this a class of bug that cannot recur — any future error in
(1), or in pricing, or in ordering, ends in a square rather than an unfunded
overnight position.
"""

from __future__ import annotations

import inspect

from app.services import position_service as ps


PLAN = inspect.getsource(ps._fifo_carry_plan)
SWEEP = inspect.getsource(ps.convert_intraday_to_carry)


# ── 2. the wallet is the authority ──────────────────────────────────────────

def test_an_unfundable_leg_is_squared_not_left_in_mis():
    assert "_force_square_whole(pos, \"CARRY_FORWARD_FAIL\")" in SWEEP
    # and it counts as a close, not as "skipped and forgotten"
    i = SWEEP.index("_force_square_whole(pos,")
    assert "force_closed += 1" in SWEEP[i : i + 200]


def test_the_square_runs_only_after_the_retry():
    # The first failure is usually just ordering — the legs that RELEASE margin
    # may come after the one that needs to BLOCK it. Squaring on the first miss
    # would close positions that the second pass funds fine.
    assert SWEEP.index("_deferred.append(") < SWEEP.index("_force_square_whole(pos,")


def test_the_forced_square_carries_a_price():
    # The rollover runs at/after the close, when the live LTP has gone to 0 and
    # the engine's zero-price block would leave the position exactly as it is —
    # which is the failure being fixed.
    src = inspect.getsource(ps._force_square_whole)
    assert "force_fill_price" in src
    assert "_exit_price(" in src


def test_the_forced_square_exits_on_the_right_side():
    # A long sells into the bid, a short lifts the ask.
    assert "_exit_action(pos)" in inspect.getsource(ps._force_square_whole)


def test_a_failed_square_is_reported_not_swallowed():
    src = inspect.getsource(ps._force_square_whole)
    assert "carry_force_square_failed" in src
    assert "return False" in src


def test_the_sweep_reports_anything_still_in_mis():
    # Every path either flips or squares, so a survivor means one failed
    # silently. That is how a night at intraday leverage went unnoticed.
    assert "carry_left_in_mis" in SWEEP
    assert '"left_in_mis"' in SWEEP


# ── 1. the plan pays for its own squares ────────────────────────────────────

def test_the_plan_prices_the_brokerage_each_square_books():
    assert "_brokerage_from_netting" in PLAN
    assert '"sq_charge"' in PLAN


def test_a_square_frees_its_margin_less_that_brokerage():
    assert "net = m - r.get(\"sq_charge\", ZERO)" in PLAN
    # and the whole-square branch advances by the NET, not the gross margin
    i = PLAN.index("net = m - ")
    assert "released += net" in PLAN[i : i + 400]


def test_the_boundary_leg_is_sized_on_the_net_too():
    # Sizing the partial on the gross would re-introduce the same shortfall on
    # the one leg the plan cuts to fit.
    assert "frac_carry = (net - gap) / net" in PLAN
    assert "* net if r[\"qty\"] > 0 else net" in PLAN


def test_an_unpriceable_charge_does_not_drop_the_leg():
    # Failing to price a charge must not remove a position from the portfolio
    # total — that would silently change how much gets squared.
    i = PLAN.index("_brokerage_from_netting")
    tail = PLAN[i : i + 400]
    assert "sq_charge = ZERO" in tail
    assert "continue" not in tail
