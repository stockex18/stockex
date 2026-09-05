"""A quantity must not print as 1429.9999999999998.

Reported off the positions screen:

    COPPER26SEP1400CE   MCX   SELL   NRML   1429.9999999999998

The FIFO walks that pair opening fills against closing ones are float
arithmetic — `sq - consume`, over and over — and float subtraction does not
close. 1430 came out the other side 2e-13 light.

The display was the visible half. The damaging half is the close path: it takes
`min(leftover, |position.quantity|)` as an order's `force_quantity`, so asking
to close the whole position closed 1429.9999999999998 of it and left a 2e-13
dust position open behind — a row that can never be cleared by closing it
again, because closing it again would leave dust of its own.

One helper at the four points a FIFO result escapes, rather than converting the
walks to Decimal: the leftovers flow straight into float margin and P&L maths
downstream, so the conversion would ripple through both modules for an artefact
that lives at 1e-13.
"""

from __future__ import annotations

import inspect

from app.utils.decimal_utils import clean_qty


def test_the_reported_value():
    assert clean_qty(1429.9999999999998) == 1430.0


def test_noise_on_the_other_side_too():
    """Float error goes both ways; a quantity 2e-13 OVER is the same artefact
    and would print just as badly."""
    assert clean_qty(17500.000000001) == 17500.0
    assert clean_qty(1430.0000000000002) == 1430.0


def test_real_fractional_quantities_are_untouched():
    """This platform genuinely trades fractions — MCX 231.5 and 63.75 are on
    the operator's own screen. Rounding to whole numbers would corrupt them."""
    for v in (231.5, 63.75, 231.3, 0.00012345, 188.2, 0.5):
        assert clean_qty(v) == v, v


def test_zero_stays_zero():
    assert clean_qty(0.0) == 0.0


def test_the_precision_sits_between_the_noise_and_the_smallest_real_step():
    """8 decimals: far below any tradeable step here, far above the ~1e-13 the
    noise lives at. If either of those ever meets in the middle this test is
    where it shows."""
    assert clean_qty(1e-13) == 0.0          # noise collapses
    assert clean_qty(1e-8) == 1e-8          # a real step survives


# ── every escape hatch is covered ─────────────────────────────────────
def test_the_active_tab_cleans_its_fifo_leftover():
    from app.api.v1.user import positions as api

    src = inspect.getsource(api.list_active_trades)
    assert "remaining_qty[str(t.id)] = clean_qty(leftover)" in src
    assert "tq = clean_qty(min(float(t.quantity), need - accum))" in src


def test_the_close_path_cleans_it_before_it_becomes_an_order():
    """The important one. `_fifo_leftover` feeds `close_qty`, which feeds
    `force_quantity` on a real market order."""
    from app.api.v1.user import positions as api

    src = inspect.getsource(api.close_active_trade)
    assert "return clean_qty(max(0.0, lo))" in src
    assert "close_qty = min(leftover_for_target, abs(float(p.quantity)))" in src


def test_the_closed_blotter_cleans_its_paired_quantity():
    """Same float walk, and its `consume` is what the Closed tab prints."""
    from app.services import position_service as ps

    src = inspect.getsource(ps.list_closed_trade_events_fifo)
    assert '"qty": clean_qty(consume)' in src


def test_it_is_one_helper_not_four_inline_rounds():
    """The reason lives with the helper. Four bare `round(x, 8)` calls would
    lose it, and the next person would delete one as pointless."""
    src = inspect.getsource(clean_qty)
    assert "1429.9999999999998" in src
    assert "force_quantity" in src
