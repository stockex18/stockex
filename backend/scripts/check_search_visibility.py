"""Is every underlying's nearest contract actually reachable from search?

Three bugs in a row hid contracts that should have been listed — TCS showing
November instead of September, NIFTY's second expiry unreachable, NIFTY
futures gone entirely — and every one was found by a person looking at the
app. `tests/test_search_visibility_invariants.py` pins the same invariants
against a fixture, which catches a CODE regression.

This catches the other half: a DATA surprise. The catalog changes under us —
Zerodha recycles instrument tokens, an underlying picks up a weekly cycle, an
admin narrows a cap — and none of that shows up in a test.

    cd backend && source .venv/bin/activate
    python -m scripts.check_search_visibility                 # every admin pool
    python -m scripts.check_search_visibility --user CL123456

Exits non-zero when something is missing, so it can be wired to a cron or a
deploy check. Read-only: it resolves settings and reads the Kite dumps, and
writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import date

from app.api.v1.user.instruments import _make_expiry_gate
from app.api.v1.user.option_chain import (
    _effective_max_expiries,
    _resolve_expiry_settings_for_user,
)
from app.core.database import init_database
from app.core.redis_client import init_redis
from app.models.user import User, UserRole
from app.services.zerodha_service import zerodha

EXCHANGES = ("NSE", "NFO", "BFO", "MCX", "BSE")


def _cycle(it: str) -> str:
    return "FUT" if it == "FUT" else "OPT"


async def _check_user(u: User) -> list[str]:
    """Underlyings whose OWN nearest contract the gate would drop."""
    settings = await _resolve_expiry_settings_for_user(u.id)
    gate = _make_expiry_gate(
        zerodha, lambda root, ex: _effective_max_expiries(settings, root, ex)
    )

    today = date.today().isoformat()
    # (exchange, root, cycle) -> earliest live expiry on the board
    nearest: dict[tuple[str, str, str], str] = {}
    for ex_key in EXCHANGES:
        for r in zerodha._instruments_cache.get(ex_key) or ():
            it = (r.get("instrumentType") or "").upper()
            if it not in ("FUT", "CE", "PE"):
                continue
            e = str(r.get("expiry") or "")[:10]
            if not e or e < today:
                continue
            key = (
                (r.get("exchange") or ex_key).upper(),
                (r.get("name") or "").upper(),
                _cycle(it),
            )
            if key not in nearest or e < nearest[key]:
                nearest[key] = e

    bad: list[str] = []
    for (ex, root, cycle), exp in sorted(nearest.items()):
        it = "FUT" if cycle == "FUT" else "CE"
        if not gate(it, root, ex, exp):
            cap = _effective_max_expiries(settings, root, ex)
            bad.append(f"{ex} {root} {cycle} nearest {exp} is HIDDEN (cap={cap})")
    return bad


async def main(user_code: str | None) -> int:
    await init_database()
    try:
        await init_redis()
    except Exception as e:  # noqa: BLE001
        print(f"! redis: {e}")

    print("Loading Zerodha catalog…")
    for ex in EXCHANGES:
        try:
            rows = await zerodha.fetch_instruments(ex)
            print(f"  {ex}: {len(rows)}")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {ex}: {e}")

    if user_code:
        users = await User.find(User.user_code == user_code).to_list()
        if not users:
            print(f"No user {user_code}")
            return 2
    else:
        # One client per admin pool — settings resolve per chain, so checking
        # every user would repeat the same answer thousands of times.
        seen: set[str] = set()
        users = []
        for u in await User.find(User.role == UserRole.CLIENT).to_list():
            key = str(u.assigned_broker_id or u.assigned_admin_id or "-")
            if key in seen:
                continue
            seen.add(key)
            users.append(u)

    print(f"\nChecking {len(users)} pool(s)…\n")
    total = 0
    for u in users:
        bad = await _check_user(u)
        label = f"{u.user_code or u.id}"
        if bad:
            total += len(bad)
            print(f"  {label}: {len(bad)} hidden")
            for line in bad[:20]:
                print(f"      {line}")
            if len(bad) > 20:
                print(f"      … and {len(bad) - 20} more")
        else:
            print(f"  {label}: ok")

    print(f"\n{'FAIL' if total else 'PASS'} — {total} hidden nearest contract(s)")
    return 1 if total else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", dest="user_code", default=None)
    sys.exit(asyncio.run(main(ap.parse_args().user_code)))
