"""An account the house cannot vouch for does not get real money.

Reported by an admin: a 1000-coin games entry from what they believed was a
demo account had landed on the real Games House ledger.

    23/09 17:31:31   GAMES_HOUSE_SETTLE   -1000.00   Games payout · btcUpDown W#69

Exactly one such entry exists on the whole platform. The player's user row
has since been deleted, so whether `is_demo` was set at that moment cannot be
read back and this test does not claim it was. What the hunt did turn up is a
defect that produces precisely that symptom, and it is still live:

`_is_demo_user` answered False — meaning REAL, meaning the house moves — for
a user it could not find, and for any error while looking. 29 of the 45
Up/Down bets on this platform already belong to a player who no longer
exists, because deleting a demo account wipes the account and its
transactions and leaves the bets behind. Every one of those, settling late,
would have been paid out of the super admin's real wallet.

The rule is not "pay unless proven demo". It is "do not touch the real book
unless sure". Skipping a settle costs the house a stake it was owed on a
losing bet — recoverable, and logged. Paying one out is money gone.

Direction of the evidence, for whoever reads this next: of 45 Up/Down bets,
16 belong to live demo accounts, 29 to deleted ones, and ZERO to a live real
account. Every live real account has a games balance of 0. 22 winning bets
belong to deleted players and only ONE produced a house settle, so the guard
held for the other 21.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.services.games import hierarchy, wallet_service


class _Users:
    """Stands in for `User.get`, which is all the guard uses."""

    result: object = None
    raises: bool = False

    @classmethod
    async def get(cls, _id):
        if cls.raises:
            raise RuntimeError("replica set stepped down")
        return cls.result


@pytest.fixture
def guard(monkeypatch):
    import app.models.user as user_mod

    monkeypatch.setattr(user_mod, "User", _Users)
    _Users.result, _Users.raises = None, False

    def call(result=None, raises=False, user_id="6ab3b8da6cbfa43d86f7d240"):
        _Users.result, _Users.raises = result, raises
        return asyncio.run(wallet_service._is_demo_user(user_id))

    return call


# ── the two cases that used to let real money out ─────────────────────
def test_a_deleted_player_does_not_move_the_house(guard):
    """The live case. A demo account is deleted, its bets stay, and the next
    settle for one of them used to read as real."""
    assert guard(result=None) is True


def test_an_unreadable_user_does_not_move_the_house(guard):
    """A database hiccup is not evidence that this is real money."""
    assert guard(raises=True) is True


# ── and the cases that must still work exactly as before ──────────────
def test_a_demo_account_is_still_skipped(guard):
    assert guard(result=SimpleNamespace(is_demo=True)) is True


def test_a_real_account_still_settles(guard):
    """The point is not to stop the house working — a real player's win must
    still come out of the real house wallet."""
    assert guard(result=SimpleNamespace(is_demo=False)) is False


def test_a_system_settle_with_no_player_still_applies(guard):
    """Settles that name nobody are platform-level and always real."""
    assert guard(user_id=None) is False


# ── the skip has to be visible ────────────────────────────────────────
def test_both_new_skips_are_logged_loudly():
    """A demo skip is routine and logs at debug. These two are not routine:
    one means an account vanished, the other means the database could not be
    read, and both silently withhold money the house might have been owed."""
    src = inspect.getsource(wallet_service._is_demo_user)
    assert src.count("logger.warning") == 2
    assert "unknown_user" in src and "unreadable_user" in src


# ── every house settle names its player ───────────────────────────────
def test_the_hierarchy_settles_name_the_player_they_arise_from():
    """Each entry point already refuses a demo `user` at the top, so this is
    a second lock on the same door — the only one that still holds if a new
    caller is added and forgets the first."""
    for fn in (hierarchy._pay, hierarchy._unpay):
        src = inspect.getsource(fn)
        assert "user_id=related_user_id" in src, fn.__name__


def test_the_user_rebate_names_the_player_too():
    src = inspect.getsource(hierarchy.distribute_win_brokerage)
    i = src.index("Games brokerage rebate (user)")
    assert "user_id=user.id" in src[i : i + 160]


def test_a_reversal_is_skipped_wherever_the_payment_was():
    """Otherwise the house claws back a commission it never handed out."""
    src = inspect.getsource(hierarchy.reverse_profit_split)
    assert src.count("related_user_id=user.id") == 3


def test_the_entry_points_still_refuse_demo_up_front():
    """The outer guard is what actually carries the load today. It must not
    be quietly dropped on the grounds that the inner one exists."""
    for fn in (
        hierarchy.distribute_win_brokerage,
        hierarchy.distribute_profit_split,
        hierarchy.reverse_profit_split,
        hierarchy.distribute_gross_hierarchy,
    ):
        assert 'getattr(user, "is_demo", False)' in inspect.getsource(fn), fn.__name__
