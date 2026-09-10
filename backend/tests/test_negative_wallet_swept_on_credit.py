"""Money sat in MAIN while a trading wallet stayed in the red.

Operator: "if the MCX wallet balance is in the negative and I add coins to the
main wallet, it should pull them in immediately." Live, two users were in that
state at once:

    CL78781600  MCX      -11,978.83   MAIN  9,843.68
    CL27891621  NSE_BSE     -163.68   MAIN 10,000.00

The sweep that does this hangs off a CREDIT to MAIN, and it excluded
WALLET_TRANSFER outright. That exclusion was too blunt: moving money in from
another wallet IS "adding coins to main" — CL27891621 moved 10,000 from Crypto
to Main at 10:41 and the sweep never ran.

What the exclusion actually protected is narrower: do not shove the money
straight back into the wallet it just came OUT of, which would undo the user's
own transfer. So only that one wallet is skipped now.

Deliberately NOT changed: `SEGMENT_SHORTFALL_COVER_FROM_MAIN` stays OFF. Its
own comment carries an earlier operator rule — a wallet going negative on M2M
losses or brokerage must not reach into MAIN, because MAIN is the user's own
cash and draining it to paper over a loss hides the loss. That is a different
moment from this one, and both rules hold together: the loss stays where it
was incurred, and money the user later adds covers it.
"""

from __future__ import annotations

import inspect

from app.core.config import settings
from app.models.transaction import TransactionType
from app.services import segment_wallet_service as sws
from app.services import wallet_service


HOOK = inspect.getsource(wallet_service.adjust)
SWEEP = inspect.getsource(sws.sweep_negatives_from_main)


def test_a_transfer_into_main_now_sweeps():
    # The blanket exclusion is gone.
    assert "transaction_type != TransactionType.WALLET_TRANSFER" not in HOOK
    assert "if amt > ZERO:" in HOOK


def test_only_credits_sweep():
    # A debit must not trigger it — that is what keeps the sweep's own leg
    # (which debits MAIN) from re-entering and looping.
    i = HOOK.index("sweep_negatives_from_main")
    assert "if amt > ZERO:" in HOOK[:i]


def test_the_source_wallet_of_a_transfer_is_skipped():
    # Pushing it straight back would undo the user's own move.
    assert "skip_kind=_from_kind" in HOOK
    assert 'split("->")[0]' in HOOK
    assert "skip_kind and kind == skip_kind" in SWEEP


def test_a_plain_deposit_skips_nothing():
    # `_from_kind` stays None for anything that is not a transfer, so every
    # negative wallet is a candidate.
    assert "_from_kind = None" in HOOK
    i = HOOK.index("_from_kind = None")
    assert "if transaction_type == TransactionType.WALLET_TRANSFER:" in HOOK[i : i + 300]


def test_the_deepest_hole_is_filled_first():
    # A part-payment should land where it is most needed rather than be spread
    # thin across every wallet.
    assert "holes.sort(key=lambda kv: kv[1], reverse=True)" in SWEEP


def test_a_partial_cover_is_normal():
    # Whatever MAIN can spare goes in; the rest waits for the next credit.
    assert "min(deficit, free)" in SWEEP


def test_the_sweep_never_raises_into_the_deposit():
    # It hangs off somebody else's deposit and must never roll one back.
    assert "except Exception" in SWEEP
    assert "segment_wallet_sweep_hook_failed" in HOOK


def test_the_breach_time_cover_stays_off():
    # Different moment, earlier operator rule — see the module docstring.
    assert settings.SEGMENT_SHORTFALL_COVER_FROM_MAIN is False
    assert "must NOT reach into MAIN" in inspect.getsource(type(settings))


def test_transaction_type_is_still_what_marks_a_transfer():
    # The parse depends on it; if the enum member moved, the skip silently
    # stops working and the sweep starts undoing transfers.
    assert TransactionType.WALLET_TRANSFER.value == "WALLET_TRANSFER"
