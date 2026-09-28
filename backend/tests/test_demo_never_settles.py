"""Demo money never raises a settlement request, and never blocks a trade.

A settlement request asks an admin to approve funds. Against a demo wallet
that is asking them to approve money which was never real — and while the
request sits there, `order_validator` refuses every new opening trade, so a
demo account is locked out of the one thing it exists for.

Seven demo users were carrying `auto_settlement = False` on 28 Sept, so this
was not one stray account waiting to happen. Two guards, because either one
alone leaves a hole: the wallet stops raising them, and the validator
ignores any that were raised before it did.
"""

from __future__ import annotations

import inspect

from app.services import order_validator, wallet_service


def test_a_demo_wallet_always_settles_itself():
    src = inspect.getsource(wallet_service.adjust)
    i = src.index("auto_settlement_on = bool(")
    # The demo override must come AFTER the flag is read, or the user's own
    # setting would win and the request would still be raised.
    j = src.index('is_demo', i)
    k = src.index("auto_settlement_on = True", j)
    assert i < j < k


def test_the_validator_lets_a_demo_account_open_trades():
    src = inspect.getsource(order_validator.validate)
    gate = src[src.index("Settlement-pending gate") :]
    head = gate[: gate.index("has_pending_settlement_request")]
    assert "is_demo" in head, "the gate must exempt demo before it probes"


def test_the_block_still_stands_for_a_real_account():
    # The exemption is demo-only. A funded account that has gone negative
    # still waits for the admin, which is the whole point of the feature.
    src = inspect.getsource(order_validator.validate)
    gate = src[src.index("Settlement-pending gate") :]
    assert "SETTLEMENT_PENDING" in gate
    assert "is_reducing" in gate and "is_squareoff" in gate
