"""Cover segment wallets already sitting below zero, out of MAIN.

Two triggers keep this clean going forward: the auto-cover at the moment a
wallet breaches, and the sweep that runs whenever money lands in MAIN. Neither
helps a hole that ALREADY exists next to money that is ALREADY in MAIN — the
breach happened when MAIN was empty, and no fresh credit is coming to fire the
sweep. Live, two wallets were in exactly that state:

    CL78781600  MCX      -11,978.83   MAIN 9,843.68
    CL27891621  NSE_BSE     -163.68   MAIN 10,000.00

    cd backend && source .venv/bin/activate
    python -m scripts.cover_negative_segment_wallets            # report only
    python -m scripts.cover_negative_segment_wallets --apply    # move the money

Moves nothing MAIN cannot spare, deepest hole first so a part-payment lands
where it is most needed. Safe to re-run: a wallet already at or above zero is
skipped. Uses the platform's own transfer, so both legs are recorded as
ordinary wallet transactions and nothing is written by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal

from app.core.database import init_database
from app.core.redis_client import init_redis
from app.models.user import User
from app.models.segment_wallet import SegmentWallet
from app.services import segment_wallet_service as sws
from app.services import wallet_service, wallet_kinds
from app.utils.decimal_utils import quantize_money, to_decimal

ZERO = Decimal("0")


async def main(apply: bool) -> int:
    await init_database()
    try:
        await init_redis()
    except Exception as e:  # noqa: BLE001
        print(f"! redis: {e}")

    rows = await SegmentWallet.find_all().to_list()
    holes: dict = {}
    for w in rows:
        bal = to_decimal(w.available_balance)
        if bal < ZERO:
            holes.setdefault(w.user_id, []).append((w.kind, -bal))

    if not holes:
        print("No segment wallet is negative.")
        return 0

    print(f"{len(holes)} user(s) with a negative segment wallet\n")
    covered = shortfall = ZERO
    for user_id, items in holes.items():
        u = await User.get(user_id)
        code = (u.user_code if u else None) or str(user_id)
        mw = await wallet_service.get_or_create(user_id)
        free = to_decimal(mw.available_balance)
        items.sort(key=lambda kv: kv[1], reverse=True)  # deepest first
        print(f"  {code}  MAIN {free}")
        for kind, deficit in items:
            take = quantize_money(min(deficit, free)) if free > ZERO else ZERO
            left = deficit - take
            covered += take
            shortfall += left
            print(
                f"      {kind:<10} short {deficit:>14}"
                f"  -> {'move' if apply else 'would move'} {take:>14}"
                + (f"  ({left} still uncovered)" if left > ZERO else "")
            )
            if apply and take > ZERO:
                try:
                    await sws.transfer(user_id, wallet_kinds.MAIN, kind, take)
                except Exception as e:  # noqa: BLE001 — keep going for the rest
                    print(f"      ! {kind}: {e}")
                    continue
                free -= take

    print(f"\n{'moved' if apply else 'would move'}={covered}  still_uncovered={shortfall}")
    if not apply and covered > ZERO:
        print("Dry run. Re-run with --apply to move the money.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually move the money")
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
