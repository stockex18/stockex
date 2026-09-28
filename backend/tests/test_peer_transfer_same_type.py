"""Float only moves between admins on the SAME arrangement.

The five admin types are five different deals with the super admin -- who
takes the brokerage, who keeps the P&L, who is on patti. Float moving between
two of them carries no record of which deal it came from, so the settlement
at the far end gets worked out on terms the money never belonged to. Between
two admins on the same type there is nothing to reconcile.

Operator, 28 Sept: "same type ka admin hi fund transfer kar sake."

The super admin is exempt on either side -- it sits above the types and funds
all of them, which is how an admin gets a float to transfer in the first
place.
"""

from __future__ import annotations

import inspect

from app.models.user import UserRole
from app.services import admin_book_service, admin_fund_service

_SRC = inspect.getsource(admin_fund_service.transfer_to_admin)


def _fake(**kw):
    from types import SimpleNamespace

    base = dict(
        no_self_brokerage=False,
        is_fixed_brokerage=False,
        pnl_share_pct=0,
        role=UserRole.ADMIN,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_five_types_are_still_five():
    assert sorted(admin_book_service.ADMIN_TYPE_NAMES) == [1, 2, 3, 4, 5]


def test_type_1_and_type_2_are_told_apart():
    # Type 1 keeps nothing; type 2 runs its own book on a fixed brokerage.
    # If these ever collapsed into one number the rule would wave through a
    # transfer between two genuinely different deals.
    t1 = admin_book_service.admin_type(_fake(no_self_brokerage=True))
    t2 = admin_book_service.admin_type(_fake(is_fixed_brokerage=True, pnl_share_pct=0))
    assert t1["n"] == 1 and t2["n"] == 2


def test_the_transfer_compares_types_before_moving_any_money():
    i = _SRC.index("admin_type(actor)")
    j = _SRC.index("wallet_service.adjust", i)
    # The comparison, and its refusal, both come BEFORE the first debit.
    assert _SRC.index('a_type["n"] != t_type["n"]', i) < j
    assert _SRC.index("ValidationFailedError", i) < j


def test_the_refusal_names_both_types():
    # "Not allowed" on its own leaves the operator guessing which side is
    # wrong; the message has to carry both arrangements.
    block = _SRC[_SRC.index('a_type["n"] != t_type["n"]') :]
    assert "t_type['n']" in block and "a_type['n']" in block
    assert "t_type['label']" in block and "a_type['label']" in block


def test_the_super_admin_is_exempt_on_either_side():
    guard = _SRC[_SRC.index("if actor.role") : _SRC.index("a_type = admin_type")]
    assert "actor.role != UserRole.SUPER_ADMIN" in guard
    assert "tgt.role != UserRole.SUPER_ADMIN" in guard


def test_transferring_to_yourself_is_still_refused_first():
    assert _SRC.index("transfer funds to yourself") < _SRC.index("admin_type(actor)")
