"""Expiry settles at the close; it stays on screen until midnight.

Two operator asks, and they pull in opposite directions until you separate
them:

  1. "first me expiry ki trade close ho, uske baad wo carry forward ke liye
      margin check kare and FIFO ke hisaab se close kare us margin se jo wallet
      me bacha hoga"

  2. "if kisi stock ki expiry aaj hai to wo raat 12 baje tak watchlist aur
      search me add rahe, taki user uski price dekh paye"

One list used to drive both - settling a position, and yanking the instrument
off watchlists / the ticker / search - so a contract expiring today vanished
from the screen the moment its segment closed. They are now two moments:

    settle   at the segment's close on expiry day
    retire   only once expiry < today, i.e. after midnight
"""

from __future__ import annotations

import inspect

from app.services import expiry_cleanup as ec
from app.services import position_service as ps

SRC = inspect.getsource(ec.cleanup_expired_once)


# ── the two moments are separate ──────────────────────────────────────
def test_settling_and_retiring_are_different_lists():
    assert "to_settle = []" in SRC
    assert "to_retire = []" in SRC


def test_a_contract_expiring_today_settles_at_its_segment_close():
    """It must not survive the night, and its margin has to come back."""
    assert "market_close_time_for_segment" in SRC
    i = SRC.index("else:  # expires TODAY")
    assert "to_settle.append(_i)" in SRC[i : i + 400]
    assert "to_retire.append(_i)" not in SRC[i : i + 400]


def test_a_contract_expiring_today_stays_on_screen():
    """Watchlist, ticker and search all work off `to_retire`, which it is not
    in until tomorrow."""
    assert "retire_tokens = [str(i.token) for i in to_retire]" in SRC
    assert '{"instrument_token": {"$in": retire_tokens}}' in SRC
    assert "for t in retire_tokens:" in SRC          # unsubscribe
    assert "for inst in to_retire:" in SRC           # is_active = False


def test_yesterdays_contract_is_both_settled_and_retired():
    i = SRC.index("if _exp < today:")
    block = SRC[i : i + 200]
    assert "to_settle.append(_i)" in block
    assert "to_retire.append(_i)" in block


def test_nothing_to_do_still_returns_early():
    assert "if not to_settle and not to_retire:" in SRC


def test_the_log_separates_the_two_counts():
    """"instruments" used to mean both. A sweep that settled three positions
    and retired nothing should not read as if it retired three."""
    assert '"settled_today": len(to_settle) - len(to_retire)' in SRC
    assert '"instruments": len(to_retire)' in SRC


# ── expiry runs before the carry decides ──────────────────────────────
def test_the_carry_sweep_settles_expiries_first():
    """Its own loop runs hourly, so on its own it could land after the carry
    and leave the sweep sizing against margin that was about to be freed."""
    src = inspect.getsource(ps.intraday_to_carry_loop)
    assert "cleanup_expired_once()" in src
    assert src.index("cleanup_expired_once()") < src.index("convert_intraday_to_carry(group_set)")


def test_an_expiry_failure_does_not_block_the_carry():
    """The carry is the more urgent of the two - a position left on intraday
    margin overnight is worse than an expiry settled an hour late."""
    src = inspect.getsource(ps.intraday_to_carry_loop)
    i = src.index("cleanup_expired_once()")
    assert "carry_expiry_presettle_failed" in src[i : i + 900]


def test_it_still_runs_after_the_once_a_day_marker():
    """Otherwise a restart would re-settle and re-sweep together."""
    src = inspect.getsource(ps.intraday_to_carry_loop)
    assert src.index("_mark_rollover_done(group_name, day_key)") < src.index("cleanup_expired_once()")


# ── the closed blotter keeps them for ever ────────────────────────────
def test_closed_rows_are_not_filtered_by_the_instrument_being_active():
    """Operator: "close trade hamesha rahe, admin ke side bhi". Retiring an
    instrument sets is_active=False; if any closed-trade read filtered on that,
    a settled expiry would disappear from the blotter."""
    from app.api.v1.user import positions as api

    for fn in (api.closed_positions,):
        src = inspect.getsource(fn)
        assert "is_active" not in src


def test_the_settled_row_says_it_was_an_expiry():
    """So the blotter can tell an expiry settlement from a stop-out."""
    src = inspect.getsource(ps.settle_expired_position)
    assert "EXPIRY" in src.upper()


# ── the settlement has to leave a fill behind ─────────────────────────
def test_the_settlement_writes_a_closing_trade():
    """Operator, on CL59713825: "nifty ke expiry dikh hi nahi raha close hone
    ke baad."

    The Closed blotter is built FIFO from TRADES - it walks a position's fills
    and pairs each opening one against a closing one. The settlement closed the
    Position and booked the P&L but never wrote a closing fill, so the opening
    fill had nothing to pair with and the row never rendered. Their book that
    day, ten contracts settled at 15:44:58 with one trade each:

        NIFTY2690823700CE   14:57:27 BUY 65 @ 21.20    <- and nothing else
        NIFTY2690823750CE   14:57:53 BUY 65 @ 10.50    <- and nothing else

    while the ones the carry sweep closed had both legs and showed fine.
    """
    src = inspect.getsource(ps.settle_expired_position)
    assert "_Trade(" in src
    assert ".insert()" in src


def test_the_closing_fill_is_on_the_opposite_side():
    """A long is closed by a SELL. Getting this backwards would pair the row
    against itself and double the position in the blotter."""
    src = inspect.getsource(ps.settle_expired_position)
    assert "_close_action = _OA.SELL if qty_signed > 0 else _OA.BUY" in src


def test_it_carries_the_settlement_price_and_the_booked_pnl():
    """`realized` is already on the wallet; stamping it means the blotter shows
    that figure rather than recomputing against a price that no longer exists -
    the contract is dead and has no live quote."""
    src = inspect.getsource(ps.settle_expired_position)
    assert "price=Decimal128(str(settle))" in src
    assert "pnl_inr=Decimal128(str(realized))" in src


def test_no_brokerage_is_invented():
    """None was charged. Putting a number here would make the blotter claim a
    cost the user never paid."""
    src = inspect.getsource(ps.settle_expired_position)
    i = src.index("_Trade(")
    assert "brokerage=" not in src[i : i + 900]


def test_a_settlement_has_no_order_behind_it():
    """Nobody placed it - it closes from the clearing side."""
    from app.models.trade import Trade

    assert Trade.model_fields["order_id"].is_required() is False
    src = inspect.getsource(ps.settle_expired_position)
    assert "order_id=None," in src


def test_a_failed_trade_write_does_not_strand_the_position():
    """A missing blotter row is bad; an unsettled expired position still
    holding margin is worse."""
    src = inspect.getsource(ps.settle_expired_position)
    i = src.index("_Trade(")
    tail = src[i : i + 1400]
    assert "except Exception" in tail
    assert "expiry_settlement_trade_write_failed" in tail


def test_the_trade_is_written_before_the_position_is_flattened():
    """`closed_qty` and `qty_signed` are read from the position; step 3 sets
    quantity to 0."""
    src = inspect.getsource(ps.settle_expired_position)
    assert src.index("_Trade(") < src.index("pos.quantity = 0.0")


# ── the settlement price is the one it could exit at ──────────────────
def test_expiry_settles_on_the_exit_side_not_the_ltp():
    """Operator: "expiry me trade LTP me close hoti hai, usko ask and bid me
    set karo."

    The LTP is a print, not an offer. On the thin, about-to-die contracts an
    expiry deals with it can sit well away from either side of the book, so the
    position was settled at a price it could not have been closed at.
    """
    src = inspect.getsource(ps.settle_expired_position)
    assert "await _exit_price(token, _exit_action(pos), _live)" in src


def test_the_ltp_is_the_fallback_not_the_first_choice():
    """`_exit_price` returns what it is handed when the book is missing or
    crossed, so the LTP stays second."""
    src = inspect.getsource(ps.settle_expired_position)
    i = src.index("_exit_price(token,")
    assert "_live" in src[i - 400 : i]
    assert "market_data_service.get_ltp(token)" in src[i - 400 : i]


def test_an_explicit_settlement_price_is_still_honoured():
    """A crypto option is settled at its INTRINSIC value - 0 for one that
    expires worthless. That path must not be diverted to a book price, or an
    OTM option would settle at its last quote and the buyer would keep money
    they lost."""
    src = inspect.getsource(ps.settle_expired_position)
    i = src.index("settle = max(ZERO, settle)")
    assert "_exit_price" not in src[:i]
    assert "allow_zero" in src[:i]


def test_it_still_refuses_to_settle_at_zero_without_a_price():
    """No book, no LTP, no stored mark - leave it OPEN for a later run rather
    than book the whole notional as a loss."""
    src = inspect.getsource(ps.settle_expired_position)
    assert "expiry_settlement_skip_no_price" in src
    assert 'return "skipped"' in src


def test_the_three_close_paths_now_price_the_same_way():
    """Carry sweep, P&L marking and expiry all take the exit side. They used to
    disagree, which is how the same position showed three different numbers."""
    assert "_exit_price(" in inspect.getsource(ps.convert_intraday_to_carry)
    assert "_exit_price(" in inspect.getsource(ps.settle_expired_position)
    assert 'q.get("bid") if qty > 0 else q.get("ask")' in inspect.getsource(
        ps.refresh_unrealized_pnl
    )
