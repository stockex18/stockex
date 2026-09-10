"""A segment wallet in the red must be covered when money reaches MAIN.

Operator: "if the MCX wallet balance is in the negative and I add coins to the
main wallet, it is not pulling the coins from the main wallet into the MCX
wallet."

It wasn't. `segment_wallet_service.transfer` is a manual, user-initiated move
and nothing ever ran it on its own. Four wallets were live in this state:

    user …bfd4eb   MCX       -85,670.95   used 10,20,254.17
    user …64cdd2   MCX       -29,131.53   used         0.00
    user …0094c6   NSE_BSE    -6,722.45
    user …0cf0b4   CRYPTO     -3,347.41

The second one is the shape of the problem: no open position, so it cannot
climb out by closing anything. It just stays negative for ever.
"""

from __future__ import annotations

import inspect

from app.services import segment_wallet_service as sws
from app.services import wallet_service as ws

SRC = inspect.getsource(sws.sweep_negatives_from_main)
HOOK = inspect.getsource(ws.adjust)


# ── the sweep itself ──────────────────────────────────────────────────
def test_it_only_touches_wallets_that_are_actually_negative():
    assert "if bal < ZERO:" in SRC
    assert "wallet_kinds.SEGMENT_KINDS" in SRC


def test_it_never_moves_more_than_main_can_spare():
    """`_transferable` is the free balance — margin already locked is not
    spare, and taking it would break the positions it is holding."""
    assert "_transferable(user_id, wallet_kinds.MAIN)" in SRC
    assert "min(deficit, free)" in SRC


def test_it_stops_when_main_runs_out():
    assert "if free <= ZERO:" in SRC
    assert "free -= amt" in SRC


def test_the_deepest_hole_is_filled_first():
    """A part-payment should land where it is most needed rather than being
    spread thin across four wallets and clearing none of them."""
    assert "holes.sort(key=lambda kv: kv[1], reverse=True)" in SRC


def test_one_failed_leg_does_not_abandon_the_others():
    """A single wallet refusing the transfer must not strand the other three."""
    i = SRC.index("segment_wallet_sweep_leg_failed")
    assert "continue" in SRC[i : i + 300]


def test_it_never_raises():
    """It hangs off somebody else's deposit. An exception here would roll back
    the deposit that triggered it."""
    assert "except Exception:  # noqa: BLE001" in SRC
    assert "segment_wallet_sweep_failed" in SRC


def test_every_move_is_logged():
    """Money moving on its own, with no user action behind it, has to leave a
    record naming the wallet and the amount."""
    assert "segment_wallet_swept" in SRC
    assert 'moved.append({"kind": kind, "amount": str(amt), "deficit": str(deficit)})' in SRC


def test_it_goes_through_the_normal_transfer():
    """Not a raw balance write — `transfer` books both legs as
    WALLET_TRANSFER ledger entries and reverts the debit if the credit fails."""
    assert "await transfer(user_id, wallet_kinds.MAIN, kind, amt)" in SRC


# ── the hook ──────────────────────────────────────────────────────────
def test_it_runs_on_a_credit_to_the_main_wallet():
    assert "sweep_negatives_from_main(user_id, skip_kind=_from_kind)" in HOOK
    assert "if amt > ZERO:" in HOOK


def test_only_the_source_wallet_of_a_transfer_is_excluded():
    """Moving money OUT of a segment wallet credits MAIN, and sweeping it
    straight back would undo the user's own transfer.

    Excluding EVERY transfer was too blunt, though: moving money in from
    another wallet is the operator's own example of adding coins to main —
    live, 10,000 came in from Crypto while NSE/BSE sat at -163.68 and the
    sweep never ran. Only the wallet the money came out of is skipped now.
    """
    i = HOOK.index("sweep_negatives_from_main")
    assert "TransactionType.WALLET_TRANSFER" in HOOK[i - 400 : i]
    assert 'split("->")[0]' in HOOK
    assert "skip_kind and kind == skip_kind" in inspect.getsource(
        sws.sweep_negatives_from_main
    )


def test_the_sweeps_own_leg_cannot_re_enter_the_hook():
    """It debits MAIN, and the hook only fires on a credit — so even without
    the transfer-type guard there is no recursion. Both hold."""
    assert "if amt > ZERO" in HOOK
    src = inspect.getsource(sws.transfer)
    assert "wallet_service.adjust(user_id, -amt" in src


def test_the_hook_cannot_break_the_deposit_it_hangs_off():
    i = HOOK.index("sweep_negatives_from_main")
    tail = HOOK[i : i + 400]
    assert "except Exception:" in tail
    assert "segment_wallet_sweep_hook_failed" in tail
