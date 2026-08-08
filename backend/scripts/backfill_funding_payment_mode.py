"""Backfill payment_mode="CASH" on existing admin-funding ledger rows that
predate the payment-mode feature (operator: "abhi jo direct add hua hai ve
cash type se entry kar dena").

Targets ADMIN_DEPOSIT rows with no payment_mode set. Idempotent.

    python -m scripts.backfill_funding_payment_mode          # apply
    python -m scripts.backfill_funding_payment_mode --dry    # count only
"""
import asyncio
import sys

from app.core.database import init_database
from app.models.transaction import TransactionType, WalletTransaction


async def main(dry: bool):
    await init_database()
    coll = WalletTransaction.get_motor_collection()
    q = {
        "transaction_type": TransactionType.ADMIN_DEPOSIT.value,
        "$or": [{"payment_mode": {"$exists": False}}, {"payment_mode": None}],
    }
    n = await coll.count_documents(q)
    print(f"ADMIN_DEPOSIT rows missing payment_mode: {n}")
    if dry:
        print("dry run — nothing written")
        return
    res = await coll.update_many(q, {"$set": {"payment_mode": "CASH"}})
    print(f"updated {res.modified_count} rows -> payment_mode=CASH")


if __name__ == "__main__":
    asyncio.run(main("--dry" in sys.argv))
