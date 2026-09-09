"""The balance and the M2M beside it must be the same number.

Admin: "M2M ke hisaab se balance galat show ho raha hai."

He was right, and the arithmetic of the tiles was not the problem - that adds
up exactly:

    BALANCE   = stored cash + floating P&L
    AVAILABLE = available_balance + credit_limit + floating P&L
    USED      = used_margin          (and the MARGIN column sums to it)

The problem was WHICH PRICE each side used. The M2M in the positions table
comes from `refresh_unrealized_pnl`, which has always marked at the CLOSE side
- bid for a long, ask for a short. The float folded into the balance came from
`segment_float_pnl`, which marked at the LTP. Measured on a three-leg MCX book:

    balance float (LTP)      1,13,832.90
    M2M column (exit side)   1,14,473.70
                                   640.80 apart

Not cosmetic: this figure feeds the AVAILABLE tile, `block_margin`, the order
validator's buying power and the overnight carry budget, so all of them were
sizing against a price the position could not actually be closed at.
"""

from __future__ import annotations

import inspect

from app.services import position_service as ps
from app.services import segment_wallet_service as sws

SRC = inspect.getsource(sws.segment_float_pnl)


def test_it_marks_at_the_close_side():
    assert 'side_raw = q.get("bid") if qty > 0 else q.get("ask")' in SRC


def test_it_agrees_with_the_m2m_the_user_reads():
    """Same rule, same words, in both places - if these ever drift again the
    balance and the M2M drift with them."""
    other = inspect.getsource(ps.refresh_unrealized_pnl)
    assert 'q.get("bid") if qty > 0 else q.get("ask")' in other
    assert 'q.get("bid") if qty > 0 else q.get("ask")' in SRC


def test_a_missing_book_still_falls_back_to_the_ltp():
    """Illiquid contracts and equity feeds with no depth publish no book. The
    LTP is the next best thing, exactly as before."""
    i = SRC.index("if side > 0:")
    assert 'mark = to_decimal(q.get("ltp") or 0)' in SRC[i : i + 400]


def test_the_stored_mark_and_stored_pnl_remain_the_last_resorts():
    """The chain that stopped free-margin silently doing nothing when mdlive
    missed - it must survive the change."""
    assert "mark = to_decimal(p.ltp)" in SRC
    assert "to_decimal(p.unrealized_pnl)" in SRC


def test_a_quote_failure_cannot_take_the_wallet_down():
    """This runs on the order path. One bad token must not fail the batch."""
    assert "return_exceptions=True" in SRC
    assert "isinstance(q, Exception)" in SRC


def test_it_is_still_one_batched_round_trip():
    """It is called from `block_margin` and the validator - a per-position
    await would put N sequential fetches on the order path."""
    assert "_asyncio.gather(" in SRC


def test_zero_and_none_are_not_treated_as_a_price():
    """A book that publishes 0 is a book that is absent."""
    assert 'side_raw not in (None, 0, "0")' in SRC


# ── everything that reads it now agrees ───────────────────────────────
def test_the_places_this_feeds_are_the_reason_it_matters():
    from app.services import order_validator as ov

    assert "segment_float_pnl" in inspect.getsource(ov.validate)
    assert "segment_float_pnl" in inspect.getsource(sws.block_margin)
    assert "segment_float_pnl" in inspect.getsource(ps._segment_float)
