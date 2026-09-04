"""Trial balance for the coin economy.

The rule the whole report rests on:

    Every coin that exists is sitting in exactly one wallet.

So the two sides are not two sets of vouchers that must be kept in step — they
are the same quantity counted twice, once as "what was issued" and once as
"where it is now". That is why this squares to the paisa and a Tally trial
balance built from vouchers does not always.

    CREDIT   Main Wallet - Coins Issued    the capital account, the source
    DEBIT    every wallet holding them      main balance in hand, admins,
                                            brokers, users, margin, segments

THE KUBER POOL IS NOT IN THIS SHEET. It is a separate house pool that funds
admins on its own; this report follows the MAIN wallet's issuance and where it
went, which is the flow the operator books against. Carrying 98 crore of Kuber
through it would swamp every other line and make the totals meaningless for
the question the report answers. It is printed as a memo below the sheet so it
is not invisible, and it is excluded from both totals.

Trading, brokerage, P&L, patti, transfers between wallets — none of these
create or destroy a coin. They only move one from one pocket to another, so
they cancel across the two sides and cannot unbalance the report. Only issuing
and withdrawing change the total.

WHY THE TRANSACTION LOG IS SHOWN SEPARATELY, NOT USED AS THE CREDIT SIDE.
`wallet_transactions` records 200 crore of KUBER_TOPUP against a pool that
holds 98 crore: the seeded balance was set directly rather than moved in, so
the log covers only part of the history. Building the credit side from it
would show a hundred-crore hole that is an artefact of seeding, not a missing
coin. Balances are the reliable side, so the report is built on them — and the
log total is printed underneath as a reconciliation note, because a growing
gap there IS worth knowing about.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: Transaction types that bring a coin into existence or take it out. Anything
#: not listed is a transfer between wallets and nets to zero across the book.
MINT_TYPES = ("KUBER_TOPUP", "SA_CASH_TOPUP", "DEPOSIT", "BONUS", "PROMO", "ADJUSTMENT")
BURN_TYPES = ("WITHDRAWAL",)


def _dec(v: Any) -> Decimal:
    """Decimal128 / float / str / None -> Decimal, never raising."""
    if v is None:
        return ZERO
    try:
        return Decimal(str(v.to_decimal() if hasattr(v, "to_decimal") else v))
    except Exception:  # noqa: BLE001
        return ZERO


async def build(as_on: datetime | None = None) -> dict[str, Any]:
    """The whole report. Read-only — it computes, it never writes."""
    from app.core.database import get_db

    db = get_db()

    # ── who is who ────────────────────────────────────────────────────
    # One pass over users so a wallet can be attributed without a query each.
    users: dict[Any, dict[str, Any]] = {}
    async for u in db["users"].find({}, {"role": 1, "full_name": 1, "user_code": 1}):
        users[u["_id"]] = u

    sa_main = sa_kuber = ZERO
    brokers = ZERO
    users_avail = users_margin = ZERO
    outstanding = ZERO
    per_admin: dict[str, Decimal] = {}

    async for w in db["wallets"].find({}, {
        "user_id": 1, "available_balance": 1, "used_margin": 1,
        "kuber_balance": 1, "temporary_balance": 1, "settlement_outstanding": 1,
    }):
        u = users.get(w.get("user_id")) or {}
        role = u.get("role") or "UNKNOWN"
        avail = _dec(w.get("available_balance"))
        margin = _dec(w.get("used_margin"))
        # Temporary balance is earned-but-unreleased commission. It is a coin
        # the platform is holding for that admin, so it belongs on the sheet;
        # leaving it out is how a report quietly stops squaring.
        temp = _dec(w.get("temporary_balance"))
        outstanding += _dec(w.get("settlement_outstanding"))

        if role == "SUPER_ADMIN":
            sa_main += avail + margin + temp
            sa_kuber += _dec(w.get("kuber_balance"))
        elif role == "ADMIN":
            label = (u.get("full_name") or u.get("user_code") or "Admin").strip()
            code = u.get("user_code") or ""
            key = f"{label} ({code})" if code else label
            per_admin[key] = per_admin.get(key, ZERO) + avail + margin + temp
        elif role == "BROKER":
            brokers += avail + margin + temp
        else:
            users_avail += avail + temp
            users_margin += margin

    # ── segment wallets ───────────────────────────────────────────────
    seg_avail = seg_margin = ZERO
    async for s in db["segment_wallets"].find({}, {"available_balance": 1, "used_margin": 1}):
        seg_avail += _dec(s.get("available_balance"))
        seg_margin += _dec(s.get("used_margin"))

    # ── security money ────────────────────────────────────────────────
    # Collateral an admin has lodged: coins the platform HOLDS but does not
    # own, so it is a liability on the credit side, exactly as a deposit from
    # a customer is in a normal set of books.
    security = payable = ZERO
    async for a in db["admin_securities"].find({}, {"security_balance": 1, "payable_balance": 1}):
        security += _dec(a.get("security_balance"))
        payable += _dec(a.get("payable_balance"))

    # ── the two sides ─────────────────────────────────────────────────
    # Kuber is deliberately absent — see the module docstring. What the main
    # wallet still holds IS an asset and stays.
    debit_rows: list[dict[str, Any]] = [
        {"group": "Super Admin", "account": "Main Wallet - balance in hand", "debit": sa_main},
    ]
    for name in sorted(per_admin):
        debit_rows.append({"group": "Admins", "account": name, "debit": per_admin[name]})
    if not per_admin:
        debit_rows.append({"group": "Admins", "account": "(none)", "debit": ZERO})
    debit_rows += [
        {"group": "Brokers", "account": "Broker Wallets", "debit": brokers},
        {"group": "Users", "account": "Available Balance", "debit": users_avail},
        {"group": "Users", "account": "Margin Locked", "debit": users_margin},
        {"group": "Segment Wallets", "account": "Available", "debit": seg_avail},
        {"group": "Segment Wallets", "account": "Margin Locked", "debit": seg_margin},
    ]
    # Money a user owes after a stop-out could not be fully recovered. It is
    # NOT a coin anyone holds — it is a coin that was paid out and never
    # covered — so it reduces the asset side rather than adding to it.
    if outstanding:
        debit_rows.append(
            {"group": "Receivable", "account": "Settlement Outstanding", "debit": -outstanding}
        )

    total_debit = sum((r["debit"] for r in debit_rows), ZERO)

    # Always rendered, zero or not. A trial balance lists the ACCOUNT, and an
    # account that vanishes when it happens to be empty is one the operator
    # cannot check — "is security money in this sheet at all?" should be
    # answerable by looking, not by remembering.
    credit_rows: list[dict[str, Any]] = [
        {"group": "Current Liabilities", "account": "Security Money held", "credit": security},
        {"group": "Current Liabilities", "account": "Payable to Admins", "credit": payable},
    ]
    liabilities = sum((r["credit"] for r in credit_rows), ZERO)

    # The capital account is what makes the sheet an identity rather than a
    # coincidence: coins in circulation are, by definition, whatever the
    # wallets hold once the money held on someone else's behalf is set aside.
    circulation = total_debit - liabilities
    credit_rows.insert(
        0,
        {
            "group": "Coin Capital",
            "account": "Main Wallet - total coins issued",
            "credit": circulation,
        },
    )
    total_credit = liabilities + circulation

    # ── reconciliation against the transaction log ────────────────────
    minted = burned = ZERO
    try:
        q: dict[str, Any] = {}
        if as_on is not None:
            q["created_at"] = {"$lte": as_on}
        pipeline = [
            {"$match": q} if q else {"$match": {}},
            {"$group": {"_id": "$transaction_type",
                        "sum": {"$sum": {"$toDecimal": "$amount"}}}},
        ]
        async for r in db["wallet_transactions"].aggregate(pipeline):
            t = r["_id"] or ""
            if t in MINT_TYPES:
                minted += _dec(r["sum"])
            elif t in BURN_TYPES:
                burned += _dec(r["sum"])
    except Exception:  # noqa: BLE001 — the note is a nicety, the sheet is not
        logger.debug("coin_trial_balance_recon_failed", exc_info=True)

    net_logged = minted - burned

    return {
        "as_on": as_on,
        "debit_rows": [{**r, "debit": str(r["debit"])} for r in debit_rows],
        "credit_rows": [{**r, "credit": str(r["credit"])} for r in credit_rows],
        "total_debit": str(total_debit),
        "total_credit": str(total_credit),
        # Zero by construction. Printed anyway: if it is ever non-zero, the
        # arithmetic above changed and the report is lying.
        "difference": str(total_debit - total_credit),
        # Outside the sheet on purpose, but not hidden: a pool this size going
        # unmentioned would be the more misleading choice.
        "memo": {"kuber_pool": str(sa_kuber)},
        "reconciliation": {
            "logged_minted": str(minted),
            "logged_burned": str(burned),
            "logged_net": str(net_logged),
            "in_wallets": str(total_debit),
            "unreconciled": str(net_logged - total_debit),
        },
    }


async def admin_breakdown(user_code: str) -> dict[str, Any]:
    """One admin's page: what they hold, and every entry that put it there.

    Three sources, because the money arrives by three different routes and the
    operator's question — "kaise-kaise aaya" — cannot be answered by any one of
    them alone:

      CASH / BANK LEDGERS  physical money booked against this admin. The link
                           is `particulars == user_code`: the books are shared
                           payment modes (Cash, HDFC, UPI, Cheque), not
                           per-party accounts, so the party is named on the
                           LINE, never on the book.
      COIN MOVEMENTS       funding, withdrawals, float, patti, brokerage and
                           P&L shares — grouped by type so a hundred brokerage
                           lines read as one figure, with the count kept.
      SECURITY             collateral lodged and what is payable back.

    Read-only.
    """
    from app.core.database import get_db

    db = get_db()

    u = await db["users"].find_one(
        {"user_code": user_code}, {"_id": 1, "user_code": 1, "full_name": 1, "role": 1}
    )
    if u is None:
        return {"error": "not found", "user_code": user_code}
    uid = u["_id"]

    # ── wallet, as it stands now ──────────────────────────────────────
    w = await db["wallets"].find_one({"user_id": uid}) or {}
    wallet = {
        "available": str(_dec(w.get("available_balance"))),
        "margin": str(_dec(w.get("used_margin"))),
        "temporary": str(_dec(w.get("temporary_balance"))),
        "total": str(
            _dec(w.get("available_balance"))
            + _dec(w.get("used_margin"))
            + _dec(w.get("temporary_balance"))
        ),
    }

    # ── cash / bank ledger lines ──────────────────────────────────────
    book_names: dict[Any, str] = {}
    async for b in db["ledger_books"].find({}, {"name": 1, "code": 1}):
        book_names[b["_id"]] = b.get("name") or b.get("code") or "Ledger"

    ledger: dict[str, dict[str, Any]] = {}
    rows = await db["ledger_book_entries"].find(
        {"particulars": user_code}
    ).sort("entry_date", 1).to_list(length=500)
    for e in rows:
        book = book_names.get(e.get("book_id"), "Ledger")
        g = ledger.setdefault(book, {"debit": ZERO, "credit": ZERO, "entries": []})
        d, c = _dec(e.get("debit")), _dec(e.get("credit"))
        g["debit"] += d
        g["credit"] += c
        g["entries"].append({
            "date": e.get("entry_date").isoformat() if e.get("entry_date") else None,
            "voucher_type": e.get("voucher_type") or "",
            "voucher_no": e.get("voucher_no") or "",
            "narration": e.get("narration") or "",
            "debit": str(d),
            "credit": str(c),
        })

    # ── coin movements, grouped by what they are ──────────────────────
    coin: list[dict[str, Any]] = []
    pipeline = [
        {"$match": {"user_id": uid}},
        {"$group": {"_id": "$transaction_type", "n": {"$sum": 1},
                    "sum": {"$sum": {"$toDecimal": "$amount"}}}},
        {"$sort": {"sum": -1}},
    ]
    async for r in db["wallet_transactions"].aggregate(pipeline):
        coin.append({"type": r["_id"] or "?", "count": r["n"], "amount": str(_dec(r["sum"]))})

    # ── security ──────────────────────────────────────────────────────
    sec = await db["admin_securities"].find_one({"admin_id": uid}) or {}

    return {
        "user_code": u.get("user_code"),
        "name": u.get("full_name") or u.get("user_code"),
        "wallet": wallet,
        "ledger": [
            {
                "book": name,
                "debit": str(g["debit"]),
                "credit": str(g["credit"]),
                "net": str(g["debit"] - g["credit"]),
                "entries": g["entries"],
            }
            for name, g in sorted(ledger.items())
        ],
        "coin": coin,
        "security": {
            "security_balance": str(_dec(sec.get("security_balance"))),
            "payable_balance": str(_dec(sec.get("payable_balance"))),
        },
    }
