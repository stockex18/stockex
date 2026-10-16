"""House page "Games net": a reversed games settle nets out.

Production: a 1,000 btcUpDown W#69 payout was booked from a demo account and
later given back to the super-admin wallet as a REVERSAL (reference GAMES_HOUSE).
The wallet was right; the card only summed GAMES_HOUSE_SETTLE and kept showing
"house down 1,000".
"""

import asyncio
import types
from decimal import Decimal

from bson import Decimal128, ObjectId

from app.api.v1.admin import me

SA = ObjectId()
ROWS = [
    {"user_id": SA, "transaction_type": "GAMES_HOUSE_SETTLE", "reference_type": "GAMES_HOUSE", "amount": "-1000.00"},
    {"user_id": SA, "transaction_type": "REVERSAL", "reference_type": "GAMES_HOUSE", "amount": "1000.00"},
    # Not games: an ordinary reversal and someone else's settle stay out.
    {"user_id": SA, "transaction_type": "REVERSAL", "reference_type": "DEPOSIT", "amount": "500.00"},
    {"user_id": ObjectId(), "transaction_type": "GAMES_HOUSE_SETTLE", "reference_type": "GAMES_HOUSE", "amount": "70.00"},
]


def _hit(row, cond):
    if "$or" in cond:
        return any(_hit(row, c) for c in cond["$or"]) and _hit(row, {k: v for k, v in cond.items() if k != "$or"})
    return all(row.get(k) == v for k, v in cond.items())


class _Agg:
    def __init__(self, out):
        self.out = out

    async def to_list(self, n):
        return self.out


def _games_coll():
    def aggregate(pipeline):
        rows = [r for r in ROWS if _hit(r, pipeline[0]["$match"])]
        net = sum((Decimal(r["amount"]) for r in rows), Decimal("0"))
        return _Agg([{"net": Decimal128(net)}])

    return types.SimpleNamespace(aggregate=aggregate, count_documents=None)


def _wallet_coll():
    async def count(q):
        return 0

    return types.SimpleNamespace(aggregate=lambda p: _Agg([]), count_documents=count)


def test_the_reversed_demo_payout_nets_to_zero(monkeypatch):
    async def get_or_create(uid):
        z = Decimal128("0")
        return types.SimpleNamespace(
            available_balance=z, settlement_outstanding=z, kuber_balance=z, kuber_total_in=z, kuber_total_out=z
        )

    monkeypatch.setattr(me.wallet_service, "get_or_create", get_or_create)
    monkeypatch.setattr(me.WalletTransaction, "get_motor_collection", classmethod(lambda cls: _games_coll()))
    monkeypatch.setattr(me.Wallet, "get_motor_collection", classmethod(lambda cls: _wallet_coll()))
    out = asyncio.run(me.house_summary(types.SimpleNamespace(id=SA)))
    assert out.data["games_net"] == 0
