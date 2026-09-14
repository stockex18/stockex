"""Patti sharing — admin-hierarchy trading P&L cascade (mirrors D:\\Stockex).

When a user in a PATTI-ENABLED subtree closes a trade, the house result of
that trade (house gains a user's loss, keeps brokerage) is shared, in
real time, up the admin/broker/sub-broker chain per each node's configured
`patti_sharing.segments[seg].{pnl_pct, brokerage_pct}`.

Design (SAFE + additive):
  • OPT-IN — fires only when the user's ADMIN-tier chain has a node with
    `patti_sharing.enabled` (default off → zero behaviour change / no double
    count with the weekly `pnl_sharing` agreement).
  • Funded from the SUPER_ADMIN house wallet (like games hierarchy). SA main
    is debited for each admin credit; SA keeps the (implicit) remainder and may
    go negative (house model). Credits land in each node's MAIN wallet.
  • SIGNED house result — the result (−realized_pnl) is shared BOTH ways: on a
    user LOSS the chain is credited; on a user PROFIT the chain is DEBITED
    (patti partners share the downside, house recovers), mirroring the
    reference `pattiTradeSettlement.js`. Brokerage is a pure positive house gain.
  • PARENT-NET cascade — each node's configured `pnl_pct`/`brokerage_pct` is its
    GROSS share of the full pool; a node NETS its own% minus the nearest
    downline's% (so a multi-level chain never distributes >100% of the pool).
    SA keeps the remainder implicitly (it IS the house). Mirrors
    `resolvePattiCascadeCredits` (reference).
  • Best-effort — a patti failure must NEVER break a trade close (caller wraps
    too).
"""

from __future__ import annotations

import logging

from beanie import PydanticObjectId

from app.models.transaction import TransactionType
from app.models.user import User
from app.services import wallet_service
from app.utils.decimal_utils import ZERO, quantize_money, to_decimal

logger = logging.getLogger(__name__)


async def _resolve_chain(user: User) -> list[User]:
    """Admin-tier ancestors above `user`, nearest → root: [sub_broker?, broker?,
    admin?]. Reuses the same resolution as games hierarchy."""
    from app.services.games import hierarchy

    chain = await hierarchy._resolve_chain(user)
    out: list[User] = []
    for key in ("sub_broker", "broker", "admin"):
        node = chain.get(key)
        if node is not None:
            out.append(node)
    return out


def _share_for(node: User, segment_key: str):
    """This node's PattiSegmentShare for the segment (or the 'ALL' fallback),
    or None when the node has no patti config."""
    ps = getattr(node, "patti_sharing", None)
    if ps is None or not ps.enabled:
        return None
    return ps.segments.get(segment_key) or ps.segments.get("ALL")


async def distribute_patti_on_close(
    user: User, realized_pnl, brokerage, instrument_segment: str | None, trade_id: str
) -> None:
    """Cascade the house result of one closing trade up the admin chain.
    `realized_pnl` is the user's signed realized P&L (negative = user lost).
    A demo account's result is virtual and never cascades."""
    if getattr(user, "is_demo", False):
        return
    try:
        from app.services import netting_service, wallet_kinds

        chain = await _resolve_chain(user)
        if not chain:
            return
        # Patti fires only if SOME node in the chain has it enabled.
        seg_key = {"MCX": "mcx", "CRYPTO": "crypto", "FOREX": "forex"}.get(
            wallet_kinds.wallet_kind_for_segment(instrument_segment), "trading"
        )
        if not any(_share_for(n, seg_key) for n in chain):
            return

        sa_id = await netting_service._resolve_super_admin_id()
        if sa_id is None:
            return

        # SIGNED house result. house gains a user's LOSS (positive) and eats a
        # user's PROFIT (negative → the chain is debited, house recovers).
        house_pnl = -to_decimal(realized_pnl)
        # Brokerage is always a positive house gain (user pays it either way).
        brok = to_decimal(brokerage)
        brok = brok if brok > ZERO else ZERO

        # Parent-net cascade (nearest → root). Each node's configured pct is its
        # GROSS share of the full pool; it nets its own% minus the immediate
        # downline's% so the chain never over-distributes. SA (house) keeps the
        # remainder implicitly. Mirrors resolvePattiCascadeCredits (reference).
        prev_pnl_pct = ZERO
        prev_brok_pct = ZERO
        for node in chain:  # nearest (sub_broker) → root (admin)
            share = _share_for(node, seg_key)
            gross_pnl_pct = to_decimal(share.pnl_pct) if share else ZERO
            gross_brok_pct = to_decimal(share.brokerage_pct) if share else ZERO
            if share is not None:
                net_pnl_pct = gross_pnl_pct - prev_pnl_pct
                net_brok_pct = gross_brok_pct - prev_brok_pct
                net_pnl_pct = net_pnl_pct if net_pnl_pct > ZERO else ZERO
                net_brok_pct = net_brok_pct if net_brok_pct > ZERO else ZERO
                pnl_amt = quantize_money(house_pnl * net_pnl_pct / to_decimal(100))
                brok_amt = quantize_money(brok * net_brok_pct / to_decimal(100))
                if pnl_amt != ZERO:  # signed — may debit the node on user profit
                    await _pay(sa_id, node.id, pnl_amt, TransactionType.PATTI_PNL,
                               f"Patti P&L share — {user.user_code} ({seg_key})", trade_id)
                if brok_amt > ZERO:
                    await _pay(sa_id, node.id, brok_amt, TransactionType.PATTI_BROKERAGE,
                               f"Patti brokerage share — {user.user_code} ({seg_key})", trade_id)
            # Immediate-downline gross carries up regardless of this node's config.
            prev_pnl_pct = gross_pnl_pct
            prev_brok_pct = gross_brok_pct
    except Exception:  # noqa: BLE001 — patti must never break a trade close
        logger.exception("patti_distribute_failed user=%s trade=%s", getattr(user, "id", None), trade_id)


async def _pay(sa_id, node_id, amount, ttype: TransactionType, narration: str, trade_id: str) -> None:
    """Move a SIGNED patti share between the SA house and an admin's MAIN wallet.

    `amount > 0` → credit the node, debit the house (user lost, chain earns).
    `amount < 0` → debit the node, credit the house (user profited, chain shares
    the downside). Both sides floor at 0 + book settlement if they can't cover —
    the same house-may-go-negative model as games.
    """
    tag = "house-funded" if amount > ZERO else "house-recovered"
    # House leg is the mirror of the node leg (−amount).
    await wallet_service.adjust(
        sa_id, -amount, transaction_type=ttype,
        narration=f"{narration} ({tag})", reference_type="PATTI", reference_id=str(trade_id),
    )
    await wallet_service.adjust(
        PydanticObjectId(str(node_id)), amount, transaction_type=ttype,
        narration=narration, reference_type="PATTI", reference_id=str(trade_id),
    )
