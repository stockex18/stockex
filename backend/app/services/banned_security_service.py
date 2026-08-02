"""Banned-security resolver + admin ops.

`is_banned` / `active_ban` are hit on the hot paths (every opening-order check
and every per-position P&L refresh), so all bans are cached in-process and
refreshed on a short TTL — bans are few and change rarely.
"""

from __future__ import annotations

import time as _time
from decimal import Decimal

from beanie import PydanticObjectId
from bson import Decimal128

from app.models.banned_security import GLOBAL_SCOPE, BannedSecurity
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import now_utc

_TTL_SEC = 10.0
_cache: dict[str, list[BannedSecurity]] = {}  # token -> bans
_cache_ts: float = 0.0


async def _refresh(force: bool = False) -> None:
    global _cache, _cache_ts
    if not force and (_time.monotonic() - _cache_ts) < _TTL_SEC:
        return
    rows = await BannedSecurity.find_all().to_list()
    cache: dict[str, list[BannedSecurity]] = {}
    for r in rows:
        cache.setdefault(str(r.token), []).append(r)
    _cache = cache
    _cache_ts = _time.monotonic()


def _matches(ban: BannedSecurity, user) -> bool:
    if ban.scope == GLOBAL_SCOPE:
        return True
    return str(getattr(user, "assigned_admin_id", "") or "") == ban.scope


async def active_ban(user, token: str) -> BannedSecurity | None:
    """The ban in effect for this user × instrument, else None. Prefers whichever
    matching row exists (GLOBAL or the user's admin scope)."""
    await _refresh()
    for ban in _cache.get(str(token), []):
        if _matches(ban, user):
            return ban
    return None


async def is_banned(user, token: str) -> bool:
    return (await active_ban(user, token)) is not None


async def freeze_price_for(user, token: str) -> Decimal | None:
    """Frozen LTP for a banned instrument (P&L locks here), else None."""
    ban = await active_ban(user, token)
    if ban is None:
        return None
    fp = to_decimal(ban.freeze_price)
    return fp if fp > 0 else None


async def freeze_price_for_position(position) -> Decimal | None:
    """Hot-path variant for the per-tick P&L refresh. Fast path: a token with no
    ban returns immediately (no user fetch). Only a banned token pays for a
    User.get, and only when the ban is admin-scoped (GLOBAL resolves without it)."""
    await _refresh()
    try:
        token = str(position.instrument.token)
    except Exception:  # noqa: BLE001
        return None
    bans = _cache.get(token)
    if not bans:
        return None  # the common case — no ban on this instrument
    for b in bans:
        if b.scope == GLOBAL_SCOPE:
            fp = to_decimal(b.freeze_price)
            return fp if fp > 0 else None
    # Admin-scoped ban(s) only — resolve the position's owning admin once.
    from app.models.user import User

    u = await User.get(position.user_id)
    admin_id = str(getattr(u, "assigned_admin_id", "") or "") if u else ""
    for b in bans:
        if admin_id and admin_id == b.scope:
            fp = to_decimal(b.freeze_price)
            return fp if fp > 0 else None
    return None


# ── Super-admin ops ──────────────────────────────────────────────────
async def ban(token: str, symbol: str, scope: str, by: PydanticObjectId | None) -> BannedSecurity:
    """Ban a security. `scope` = "GLOBAL" or an admin id. Snapshots the current
    LTP as the freeze price so open positions lock their P&L there."""
    from app.services import market_data_service

    try:
        ltp = await market_data_service.get_ltp(str(token))
    except Exception:  # noqa: BLE001 — a missing LTP just means no freeze snapshot
        ltp = Decimal("0")

    existing = await BannedSecurity.find_one(
        BannedSecurity.token == str(token), BannedSecurity.scope == scope
    )
    if existing is not None:
        existing.symbol = symbol
        existing.freeze_price = Decimal128(str(to_decimal(ltp)))
        existing.banned_by = by
        existing.banned_at = now_utc()
        await existing.save()
        row = existing
    else:
        row = BannedSecurity(
            token=str(token), symbol=symbol, scope=scope,
            freeze_price=Decimal128(str(to_decimal(ltp))),
            banned_by=by, banned_at=now_utc(),
        )
        await row.insert()
    await _refresh(force=True)
    return row


async def unban(ban_id: str) -> bool:
    row = await BannedSecurity.get(PydanticObjectId(ban_id))
    if row is None:
        return False
    await row.delete()
    await _refresh(force=True)
    return True


async def list_bans() -> list[BannedSecurity]:
    return await BannedSecurity.find_all().sort("-banned_at").to_list()
