"""Delivery pledge — equity bought for delivery backs NSE/BSE F&O margin.

The operator's rules:
  • An NSE/BSE equity DELIVERY (CNC) buy takes its full value from the NSE
    wallet — no leverage — and the shares are pledged automatically.
  • Pledged shares give `haircut_pct` (default 50 %) of their value as margin
    that can ONLY open NSE/BSE F&O positions.
  • That margin never pays a loss. P&L always lands in cash, and stop-out is
    measured against cash alone.

How it sits on the B-book engine (why it touches so little):
  • "Full value" is the existing margin lock at 100 %, 1×. The lock / release /
    P&L path already turns that into "cost out on the buy, cost + P&L back on
    the sell" — the same money a real delivery trade moves — so there is no new
    wallet flow.
  • The pledge is not a stored balance. limit = Σ pledged value × haircut;
    used = Σ `pledge_margin` on open positions + pending orders. Both are
    re-derived from those rows every time, so there is nothing to drift.
  • Only CNC positions opened while the feature is ON are pledged
    (`Position.is_pledge`). Every existing position runs exactly as before.
"""

from __future__ import annotations

import time as _t
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from beanie import PydanticObjectId
from bson import Decimal128

from app.services import wallet_kinds
from app.utils.decimal_utils import quantize_money, to_decimal

ENABLED_KEY = "delivery_pledge.enabled"
HAIRCUT_KEY = "delivery_pledge.haircut_pct"
#: Comma-separated user codes. Empty = every user. Lets the operator switch the
#: feature on for one demo account before the whole book.
USERS_KEY = "delivery_pledge.user_codes"

DEFAULT_HAIRCUT = Decimal("50")
EQUITY_SEGMENTS = frozenset({"NSE_EQUITY", "BSE_EQUITY"})
_OPEN_ORDER_STATUSES = ("PENDING", "OPEN", "PARTIAL")
_ZERO = Decimal("0")

# ── Settings (60 s cache — read on every NSE order) ──────────────────────
_CACHE_TTL = 60.0
_cache: dict[str, tuple[Any, float]] = {}


async def _read(key: str, default: Any) -> Any:
    hit = _cache.get(key)
    now = _t.monotonic()
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0]
    try:
        from app.models.platform_setting import PlatformSetting

        row = await PlatformSetting.find_one(PlatformSetting.setting_key == key)
        val = row.setting_value if row is not None else default
    except Exception:  # noqa: BLE001 — a settings read must never break an order
        return default
    _cache[key] = (val, now)
    return val


def invalidate() -> None:
    """Drop the cache so a save is live on the next order, not a minute on."""
    _cache.clear()


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


async def haircut_pct() -> Decimal:
    raw = await _read(HAIRCUT_KEY, DEFAULT_HAIRCUT)
    try:
        pct = to_decimal(raw)
    except Exception:  # noqa: BLE001 — a typo falls back to the default
        return DEFAULT_HAIRCUT
    return min(max(pct, _ZERO), Decimal("100"))


async def enabled_for(user: Any) -> bool:
    if not _truthy(await _read(ENABLED_KEY, False)):
        return False
    raw = str(await _read(USERS_KEY, "") or "")
    codes = {c.strip().upper() for c in raw.replace("\n", ",").split(",") if c.strip()}
    return not codes or str(getattr(user, "user_code", "") or "").upper() in codes


# ── Classification ──────────────────────────────────────────────────────
def is_equity(segment_type: Any) -> bool:
    return str(segment_type or "").upper() in EQUITY_SEGMENTS


def is_fno(segment_type: Any) -> bool:
    """NSE / BSE futures and options — the only place pledge margin may go."""
    s = str(segment_type or "").upper()
    if not s or s in EQUITY_SEGMENTS:
        return False
    if wallet_kinds.wallet_kind_for_segment(s) != wallet_kinds.NSE_BSE:
        return False
    return "FUT" in s or "OPT" in s


async def pledge_mode(user: Any, segment_type: Any, product_type: Any, open_position: Any) -> bool:
    """Is this order on a pledged delivery position?

    An existing position keeps the mode it was opened with — adding to an old
    leveraged CNC row stays leveraged, adding to a pledged one stays pledged —
    so the margin arithmetic on one row is never mixed. Only a NEW position
    takes the switch's current state.
    """
    if str(getattr(product_type, "value", product_type)) != "CNC" or not is_equity(segment_type):
        return False
    if open_position is not None:
        return bool(getattr(open_position, "is_pledge", False))
    return await enabled_for(user)


# ── State ───────────────────────────────────────────────────────────────
def _money(v: Any) -> Decimal:
    try:
        return to_decimal(v) if v is not None else _ZERO
    except Exception:  # noqa: BLE001
        return _ZERO


@dataclass
class PledgeState:
    holdings_value: Decimal = _ZERO  # Σ pledged qty × price
    delivery_locked: Decimal = _ZERO  # cash paid for those shares (locked as margin)
    limit: Decimal = _ZERO  # holdings_value × haircut
    used: Decimal = _ZERO  # pledge backing open F&O positions + pending orders

    @property
    def available(self) -> Decimal:
        return max(_ZERO, self.limit - self.used)

    @property
    def deficit(self) -> Decimal:
        """Shares fell below the pledge in use — the gap is owed from cash."""
        return max(_ZERO, self.used - self.limit)


def compute_state(positions: list[Any], pending_orders: list[Any], haircut: Decimal) -> PledgeState:
    st = PledgeState()
    for p in positions:
        if getattr(p, "is_pledge", False):
            px = _money(getattr(p, "ltp", None))
            if px <= 0:
                px = _money(getattr(p, "avg_price", None))
            st.holdings_value += abs(to_decimal(p.quantity or 0)) * px
            st.delivery_locked += _money(getattr(p, "margin_used", None))
        st.used += _money(getattr(p, "pledge_margin", None))
    for o in pending_orders:
        st.used += _money(getattr(o, "margin_pledge", None))
    st.holdings_value = quantize_money(st.holdings_value)
    st.limit = quantize_money(st.holdings_value * haircut / Decimal(100))
    st.used = quantize_money(st.used)
    return st


async def state(user_id: Any) -> PledgeState:
    from app.models.order import Order
    from app.models.position import Position

    uid = PydanticObjectId(str(user_id))
    zero = Decimal128("0")
    positions = await Position.find(
        {
            "user_id": uid,
            "status": "OPEN",
            "$or": [{"is_pledge": True}, {"pledge_margin": {"$gt": zero}}],
        }
    ).to_list()
    orders = await Order.find(
        {
            "user_id": uid,
            "status": {"$in": list(_OPEN_ORDER_STATUSES)},
            "margin_pledge": {"$gt": zero},
        }
    ).to_list()
    return compute_state(positions, orders, await haircut_pct())


def split_margin(margin: Decimal, pledge_available: Decimal) -> Decimal:
    """The pledge share of an F&O margin — pledge first, cash for the rest.

    Pledge first keeps the cash free, and cash is what absorbs a loss.
    """
    return min(max(to_decimal(margin), _ZERO), max(to_decimal(pledge_available), _ZERO))


def sale_keeps_cover(st: PledgeState, sale_value: Decimal, haircut: Decimal) -> bool:
    """May pledged shares worth `sale_value` be sold without leaving F&O
    positions backed by collateral that is no longer there?"""
    if st.used <= 0:
        return True
    return st.limit - to_decimal(sale_value) * haircut / Decimal(100) >= st.used


# ── Risk (stop-out) ─────────────────────────────────────────────────────
def touches_pledge(positions: list[Any]) -> bool:
    return any(
        getattr(p, "is_pledge", False) or _money(getattr(p, "pledge_margin", None)) > 0
        for p in positions
    )


@dataclass
class RiskView:
    others: list[Any] = field(default_factory=list)  # what stop-out may close
    delivery_locked: Decimal = _ZERO  # take out of the cash denominator
    delivery_unrealised: Decimal = _ZERO  # take out of the floating loss
    deficit: Decimal = _ZERO  # add to the floating loss


def risk_view(positions: list[Any], haircut: Decimal) -> RiskView:
    """Stop-out sees cash and F&O only.

    Pledged shares are paid in full, so their price moves are not a loss the
    cash has to carry — they act through the pledge limit instead, and a limit
    that falls below the pledge in use comes back here as `deficit`.
    """
    st = compute_state(positions, [], haircut)
    pledged = [p for p in positions if getattr(p, "is_pledge", False)]
    return RiskView(
        others=[p for p in positions if not getattr(p, "is_pledge", False)],
        delivery_locked=st.delivery_locked,
        delivery_unrealised=sum((_money(p.unrealized_pnl) for p in pledged), _ZERO),
        deficit=st.deficit,
    )


def summary_fields(st: PledgeState, free_margin: Decimal, enabled: bool = False) -> dict[str, Any]:
    return {
        # Lets the order panel show a delivery buy at its full value.
        "pledge_enabled": bool(enabled),
        "holdings_value": str(st.holdings_value),
        "pledge_limit": str(st.limit),
        "pledge_used": str(st.used),
        "pledge_available": str(quantize_money(st.available)),
        "pledge_deficit": str(quantize_money(st.deficit)),
        # What the order panel shows for an F&O order: cash + free pledge.
        "fno_free_margin": str(quantize_money(to_decimal(free_margin) + st.available - st.deficit)),
    }
