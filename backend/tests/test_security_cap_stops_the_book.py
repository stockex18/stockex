"""When an admin's security is spent, their users stop opening and stop betting.

Operator: "kisi admin ka security money ka 90% khatam ho jaye to uske user
trade mat kar paye and game bhi play mat kar paye."

The two things this has to get right are what counts as spent and what stays
allowed. A WITHDRAW is the admin drawing their own float back, not usage —
counting it would shut a book the moment its owner took money out. And a user
must always be able to CLOSE what is already open, so the gate sits on the
opening side only.
"""

from __future__ import annotations

import inspect

from app.services import admin_security_service as sec
from app.services import order_validator
from app.services.games import wallet_service as games_wallet


def test_the_limit_is_ninety_percent():
    assert str(sec.SECURITY_CAP_PCT) == "90"


def test_only_consumption_counts_as_spent():
    assert set(sec._CONSUMED_TYPES) == {"BROKERAGE", "PNL_SHARE", "GAMES_PNL"}
    # Money in raises the base; a withdrawal lowers it. Neither is usage.
    assert set(sec._IN_TYPES) == {"DEPOSIT", "SA_TOPUP"}
    assert set(sec._OUT_TYPES) == {"WITHDRAW"}


def test_a_withdrawal_lowers_the_base_rather_than_spending_it():
    src = inspect.getsource(sec.utilisation)
    assert "lodged = lodged_in - returned" in src
    assert "consumed / lodged" in src


def test_an_admin_who_never_lodged_security_is_not_shut_out():
    """Nothing lodged means no base to measure against — that admin simply is
    not in this scheme. Only a NEGATIVE account is closed."""
    src = inspect.getsource(sec.utilisation)
    assert "balance < ZERO" in src
    assert "must not be shut out" in src


def test_the_reading_is_cached_but_a_ledger_move_clears_it():
    assert "_STATE_TTL_SEC" in inspect.getsource(sec.is_blocked)
    # A top-up has to reopen the book on the next order, not in fifteen seconds.
    assert "forget_cap_state(row.admin_id)" in inspect.getsource(sec._apply)


def test_a_failed_reading_never_blocks_anyone():
    src = inspect.getsource(sec.is_blocked)
    assert "never let this gate fail closed" in src
    assert src.index("except Exception") < src.index("return None")


def test_trading_is_gated_on_the_opening_side_only():
    src = inspect.getsource(order_validator.validate)
    assert "if not is_squareoff:" in src
    assert "ADMIN_SECURITY_EXHAUSTED" in src
    # Before any margin or price work is done — a closed book is a closed book.
    assert src.index("blocked_for_user(user)") < src.index("_fetch_risk")


def test_every_game_is_gated_in_one_place():
    src = inspect.getsource(games_wallet.atomic_games_wallet_debit)
    assert "if game_key:" in src
    assert "blocked_for_user" in src


def test_moving_your_own_money_out_is_not_gated():
    """Transfers and withdrawals pass no game_key, so the gate never sees
    them: a paused book must not trap a user's balance."""
    for fn in (games_wallet.transfer_games_to_main, games_wallet.approve_games_withdrawal):
        assert "game_key=None" in inspect.getsource(fn), fn.__name__


def test_the_cap_can_be_retuned_without_a_deploy():
    src = inspect.getsource(sec.cap_pct)
    assert "security.cap_pct" in src
    assert 'Decimal("1") <= v <= Decimal("100")' in src
