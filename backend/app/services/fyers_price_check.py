"""Order price check: Zerodha vs Fyers, at the moment a MARKET order is placed.

Added at the client's request and suggestion (Nov 2026): check
every order's price against Fyers when it is placed and report mismatches to
the super admin, without blocking any order.

Flow (see `order_service.place_order`):

  1. `start()` right after the order passes validation. It schedules a
     background task that, at the same instant, snapshots our Zerodha quote
     and asks Fyers for the same contract. The order does NOT wait for it.
  2. The order fills exactly as before.
  3. `finish()` (fire-and-forget) waits for that snapshot, applies the rule,
     saves a `FyersPriceCheck` row, and on a mismatch tells the super admin.

Nothing here can reject, delay or alter an order. If Fyers is down, slow or
not connected the row says NOT_CHECKED and trading carries on.

Compared price: the Zerodha price the order was based on — the ask for a BUY,
the bid for a SELL (LTP when that side is empty). The fill price is stored
too, but it is not what is judged: a broker's spread markup moves the fill
away from the market on purpose, and that is not a wrong feed price.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from bson import Decimal128

from app.core.redis_client import sliding_window_check
from app.models.fyers_price_check import FyersPriceCheck, PriceCheckStatus
from app.services import fyers_service, fyers_symbol_map, market_data_service
from app.services.admin_events import publish_admin_event
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# ── The rule ──────────────────────────────────────────────────────────
#: How many ticks outside the Fyers bid–ask range a price may sit before it
#: counts as a mismatch. Covers the few milliseconds between the two reads.
#: Fixed in code on purpose — change it here, not from the admin panel.
MISMATCH_TOLERANCE_TICKS = 1


def is_mismatch(
    compared: Decimal,
    *,
    fyers_bid: Decimal | None,
    fyers_ask: Decimal | None,
    fyers_ltp: Decimal | None,
    tick: Decimal,
) -> tuple[bool, Decimal] | None:
    """Is `compared` outside Fyers' bid–ask range ± the tolerance?

    Returns (mismatch, how far outside the range; 0 when inside), or None
    when Fyers gave no usable price. When Fyers has no two-sided book (a
    thin contract) its LTP stands in for both ends of the range.

    This is the ONLY place the rule lives. To change what counts as a
    mismatch, change this function (stored rows keep the raw Fyers prices,
    so old checks can be re-judged).
    """
    if fyers_bid and fyers_ask and fyers_ask >= fyers_bid:
        low, high = fyers_bid, fyers_ask
    elif fyers_ltp:
        low = high = fyers_ltp
    else:
        return None
    allow = tick * MISMATCH_TOLERANCE_TICKS
    if compared < low:
        gap = low - compared
    elif compared > high:
        gap = compared - high
    else:
        return False, Decimal(0)
    return gap > allow, gap


# ── Fyers quote sharing ───────────────────────────────────────────────
#: Orders on the same contract within this window share ONE Fyers call —
#: twenty users buying the same NIFTY option in one second cost one request.
_SHARE_WINDOW_SEC = 0.5
_inflight: dict[str, tuple[float, asyncio.Task[fyers_service.FyersQuote]]] = {}

#: Fyers allows ~10 quote calls a second per app. Stay under it across all
#: workers; a check over the limit is recorded as NOT_CHECKED, not queued
#: (a late answer no longer describes the moment of placement).
_RATE_KEY = "fyers:quote_rate"
_RATE_PER_SEC = 8


async def _rate_ok() -> bool:
    try:
        ok, _ = await sliding_window_check(_RATE_KEY, max_requests=_RATE_PER_SEC, window_sec=1)
        return ok
    except Exception:  # noqa: BLE001 — Redis trouble shouldn't turn every check off
        return True


async def _shared_quote(fyers_symbol: str) -> fyers_service.FyersQuote:
    now = time.monotonic()
    hit = _inflight.get(fyers_symbol)
    if hit and (now - hit[0]) < _SHARE_WINDOW_SEC:
        return await asyncio.shield(hit[1])
    if not await _rate_ok():
        raise fyers_service.FyersUnavailableError("Fyers rate limit (check skipped)")
    task = asyncio.create_task(fyers_service.get_quote(fyers_symbol))
    _inflight[fyers_symbol] = (now, task)
    if len(_inflight) > 500:
        for k in [k for k, (ts, _) in _inflight.items() if now - ts > _SHARE_WINDOW_SEC]:
            _inflight.pop(k, None)
    return await asyncio.shield(task)


# ── Snapshot at placement ─────────────────────────────────────────────
@dataclass
class _Snapshot:
    zerodha: dict[str, Any]
    fyers_symbol: str | None
    fyers: fyers_service.FyersQuote | None
    note: str | None
    latency_ms: int | None


async def _fyers_side(exchange: str, token: str) -> tuple[str | None, Any, str | None, int | None]:
    """(fyers_symbol, quote, reason-if-none, latency_ms)."""
    sym, reason = await fyers_symbol_map.lookup(exchange, token)
    if not sym:
        return None, None, reason, None
    t0 = time.perf_counter()
    try:
        q = await _shared_quote(sym)
    except fyers_service.FyersUnavailableError as e:
        return sym, None, str(e), int((time.perf_counter() - t0) * 1000)
    return sym, q, None, int((time.perf_counter() - t0) * 1000)


async def _zerodha_side(token: str) -> dict[str, Any]:
    try:
        return await market_data_service.get_quote(token) or {}
    except Exception:  # noqa: BLE001
        logger.warning("fyers_check_zerodha_quote_failed token=%s", token, exc_info=True)
        return {}


async def _snapshot(exchange: str, token: str) -> _Snapshot | None:
    row = await fyers_service.get_settings()
    if not row.enabled:
        return None
    (sym, q, reason, ms), zq = await asyncio.gather(
        _fyers_side(exchange, token), _zerodha_side(token)
    )
    if sym is None and reason is None:
        return None  # not a contract Fyers covers — no row at all
    return _Snapshot(zerodha=zq, fyers_symbol=sym, fyers=q, note=reason, latency_ms=ms)


def _log_snapshot_error(t: asyncio.Task[Any]) -> None:
    if not t.cancelled() and t.exception() is not None:
        logger.warning("fyers_check_snapshot_failed: %r", t.exception())


def start(instrument: Any) -> asyncio.Task[_Snapshot | None] | None:
    """Kick off the placement-time snapshot. Never raises, never awaits —
    the caller's order path is not slowed by a single round-trip."""
    try:
        exchange = str(getattr(instrument.exchange, "value", instrument.exchange) or "")
        token = str(instrument.token)
        if fyers_symbol_map.map_field(exchange, token) is None:
            return None  # crypto / forex / Infoway / index: Fyers has no price
        task = asyncio.create_task(_snapshot(exchange, token))
        # Retrieve any error even when nobody awaits the task (order failed
        # and `cancel()` came too late), so it is logged, not warned about.
        task.add_done_callback(_log_snapshot_error)
        return task
    except Exception:  # noqa: BLE001
        logger.exception("fyers_check_start_failed")
        return None


def cancel(task: asyncio.Task[Any] | None) -> None:
    """The order didn't fill — nothing to compare."""
    if task is not None and not task.done():
        task.cancel()


# ── Judge + record ────────────────────────────────────────────────────
def _d128(v: Decimal | None) -> Decimal128 | None:
    return Decimal128(str(v)) if v is not None else None


def _pos(v: Any) -> Decimal | None:
    try:
        d = to_decimal(v)
    except Exception:  # noqa: BLE001
        return None
    return d if d > 0 else None


async def finish(task: asyncio.Task[_Snapshot | None] | None, *, order: Any, trade: Any, user: Any) -> None:
    """Wait for the snapshot, judge it, save the row, alert on a mismatch.
    Run via `fire_and_forget` after the fill."""
    if task is None:
        return
    try:
        snap = await task
    except asyncio.CancelledError:
        return
    if snap is None:
        return

    action = str(getattr(order.action, "value", order.action))
    inst = order.instrument
    tick = _pos(getattr(inst, "tick_size", None)) or Decimal("0.05")

    z_ltp = _pos(snap.zerodha.get("ltp"))
    z_bid = _pos(snap.zerodha.get("bid"))
    z_ask = _pos(snap.zerodha.get("ask"))
    compared = (z_ask if action == "BUY" else z_bid) or z_ltp

    q = snap.fyers
    status = PriceCheckStatus.NOT_CHECKED
    note = snap.note
    diff: Decimal | None = None
    if q is not None and note is None:
        if compared is None:
            note = "No Zerodha price at placement"
        else:
            verdict = is_mismatch(compared, fyers_bid=q.bid, fyers_ask=q.ask, fyers_ltp=q.ltp, tick=tick)
            if verdict is None:
                note = "Fyers returned no price"
            else:
                bad, diff = verdict
                status = PriceCheckStatus.MISMATCH if bad else PriceCheckStatus.OK

    fill = _pos(getattr(trade, "price", None)) if trade is not None else None
    row = FyersPriceCheck(
        order_id=order.id,
        order_number=str(getattr(order, "order_number", "") or ""),
        trade_id=getattr(trade, "id", None),
        user_id=order.user_id,
        user_code=str(getattr(user, "user_code", "") or ""),
        user_name=str(getattr(user, "full_name", "") or ""),
        token=str(inst.token),
        symbol=str(inst.symbol),
        exchange=str(getattr(inst.exchange, "value", inst.exchange)),
        fyers_symbol=snap.fyers_symbol,
        action=action,
        quantity=float(getattr(order, "quantity", 0) or 0),
        tick_size=_d128(tick),
        zerodha_ltp=_d128(z_ltp),
        zerodha_bid=_d128(z_bid),
        zerodha_ask=_d128(z_ask),
        compared_price=_d128(compared),
        fill_price=_d128(fill),
        fyers_ltp=_d128(q.ltp if q else None),
        fyers_bid=_d128(q.bid if q else None),
        fyers_ask=_d128(q.ask if q else None),
        difference=_d128(diff),
        status=status,
        note=note,
        fyers_latency_ms=snap.latency_ms,
        placed_at=getattr(order, "created_at", None) or now_utc(),
    )
    await row.insert()

    if status == PriceCheckStatus.MISMATCH:
        logger.warning(
            "fyers_price_mismatch order=%s symbol=%s %s ours=%s fyers=%s/%s",
            row.order_number, row.symbol, action, compared, q.bid if q else None, q.ask if q else None,
        )
        # Every admin socket receives admin:events, so the payload carries no
        # user details — the super-admin page fetches those itself.
        await publish_admin_event(
            "price_mismatch",
            {"check_id": str(row.id), "symbol": row.symbol, "action": action},
        )


# ── Reads for the admin page ──────────────────────────────────────────
def _num(v: Any) -> float | None:
    # Output boundary: Decimal128 → float for JSON only.
    if v is None:
        return None
    try:
        return float(v.to_decimal() if isinstance(v, Decimal128) else v)
    except Exception:  # noqa: BLE001
        return None


def serialize(r: FyersPriceCheck) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "order_id": str(r.order_id),
        "order_number": r.order_number,
        "user_id": str(r.user_id),
        "user_code": r.user_code,
        "user_name": r.user_name,
        "symbol": r.symbol,
        "exchange": r.exchange,
        "fyers_symbol": r.fyers_symbol,
        "action": r.action,
        "quantity": r.quantity,
        "tick_size": _num(r.tick_size),
        "zerodha_ltp": _num(r.zerodha_ltp),
        "zerodha_bid": _num(r.zerodha_bid),
        "zerodha_ask": _num(r.zerodha_ask),
        "compared_price": _num(r.compared_price),
        "fill_price": _num(r.fill_price),
        "fyers_ltp": _num(r.fyers_ltp),
        "fyers_bid": _num(r.fyers_bid),
        "fyers_ask": _num(r.fyers_ask),
        "difference": _num(r.difference),
        "status": r.status.value,
        "note": r.note,
        "fyers_latency_ms": r.fyers_latency_ms,
        "placed_at": r.placed_at,
    }
