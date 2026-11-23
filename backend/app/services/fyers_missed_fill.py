"""Missed-fill alert: a resting LIMIT / SL-M order that Fyers shows the market
reaching, but that is still not filled here.

Added at the client's request (Nov 2026). The Fyers price check already looks
at every MARKET order when it is placed and every LIMIT / SL-M order when it
fills — "we filled, did Fyers agree?". This is the other half: "Fyers says
the price got there, why are we still waiting?" — a frozen or lagging feed,
a missed tick, a poller that was down.

Every `SCAN_INTERVAL_SEC` (leader worker only):

  1. Take the OPEN / PARTIAL LIMIT and SL-M orders (demo accounts skipped)
     whose market is open right now — the same gate the pending-order poller
     uses, so an order held back on a holiday or after close is never flagged.
  2. Ask Fyers for those contracts, up to 50 per request.
  3. Apply OUR OWN fill rule to Fyers' prices (`level_reached` with Fyers'
     LTP and day high / low; bid / ask are left out because the poller fills
     on the traded price, not on the quote). The day extreme only counts
     beyond the order's placement watermark, as in the poller.
  4. Wait `GRACE_SEC` and re-read those orders. Any still open at the same
     level becomes a MISSED_FILL row and the super admin is alerted.

One alert per order and level: the same order is not re-reported every
scan, but a modified order (new level) is checked afresh.

Report-only, like the rest of the Fyers check: nothing here fills, cancels
or changes an order. Fyers not connected / switched off -> no scan.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from bson import Decimal128

from app.models.fyers_price_check import FyersPriceCheck, PriceCheckStatus
from app.models.order import Order, OrderStatus, OrderType
from app.services import fyers_price_check, fyers_service, fyers_symbol_map, market_data_service
from app.services.admin_events import publish_admin_event
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

#: How often open orders are compared with Fyers. Each scan costs one Fyers
#: request per 50 contracts (none when there is nothing open), against the
#: free plan's 50 / minute and 5,000 / day shared with the order-time check.
#: Fyers' day high / low cover the time between two scans.
SCAN_INTERVAL_SEC = 60.0
#: Fyers' price can lead ours by a moment, and the poller fills within a
#: fraction of a second. An order is only reported if it is STILL open this
#: long after Fyers showed its level reached.
GRACE_SEC = 5.0
#: At most this many Fyers requests per scan (x 50 contracts). Contracts past
#: that wait for the next scan.
MAX_CALLS_PER_SCAN = 2

_OPEN = [OrderStatus.OPEN.value, OrderStatus.PARTIAL.value]
_RESTING = [OrderType.LIMIT.value, OrderType.SL_M.value]

#: (order id, level) already reported, so a still-open order is reported once.
#: Backed by the stored rows, so a restart doesn't report everything again.
_reported: set[tuple[str, str]] = set()


def _pos(v: Any) -> Decimal | None:
    try:
        d = to_decimal(v)
    except Exception:  # noqa: BLE001
        return None
    return d if d > 0 else None


def _d128(v: Decimal | None) -> Decimal128 | None:
    return Decimal128(str(v)) if v is not None else None


def _enum(v: Any) -> str:
    return str(getattr(v, "value", v))


def _level(o: Any) -> Decimal | None:
    return _pos(o.price if _enum(o.order_type) == "LIMIT" else o.trigger_price)


def judge(o: Any, q: fyers_service.FyersQuote) -> tuple[Decimal, str] | None:
    """(how far Fyers went past the level, note) when Fyers shows this resting
    order's level reached under our fill rule; None otherwise."""
    level = _level(o)
    if level is None:
        return None
    order_type, action = _enum(o.order_type), _enum(o.action)
    ref_high, ref_low = _pos(o.range_ref_high), _pos(o.range_ref_low)
    down = (order_type == "LIMIT") == (action == "BUY")
    # The poller with no placement watermark fills on the LTP alone; so do we.
    hit = fyers_price_check.level_reached(
        order_type, action, level,
        fyers_ltp=q.ltp, fyers_bid=None, fyers_ask=None,
        fyers_high=q.high if ref_high is not None else None,
        fyers_low=q.low if ref_low is not None else None,
        ref_high=ref_high, ref_low=ref_low,
    )
    if hit is None or not hit[0]:
        return None
    word = "limit" if order_type == "LIMIT" else "trigger"
    if hit[2] == "now":
        past = (level - q.ltp) if down else (q.ltp - level)  # type: ignore[operator]
        return past, f"Fyers LTP {q.ltp} reached the {word} {level}; order still open"
    extreme = q.low if down else q.high
    past = (level - extreme) if down else (extreme - level)  # type: ignore[operator]
    which = "day low" if down else "day high"
    return past, f"Fyers {which} {extreme} reached the {word} {level} (LTP now {q.ltp}); order still open"


async def _already_reported(o: Any, level: Decimal) -> bool:
    key = (str(o.id), str(level))
    if key in _reported:
        return True
    hit = await FyersPriceCheck.find_one(
        {"order_id": o.id, "status": PriceCheckStatus.MISSED_FILL.value, "level_price": _d128(level)}
    )
    if hit is not None:
        _reported.add(key)
        return True
    return False


async def _record(o: Any, fyers_symbol: str, q: fyers_service.FyersQuote, past: Decimal, note: str) -> None:
    from app.models.user import User

    level = _level(o)
    inst = o.instrument
    try:
        user = await User.get(o.user_id)
    except Exception:  # noqa: BLE001 — the row is still worth saving
        user = None
    try:
        zq = await market_data_service.get_quote(str(inst.token)) or {}
    except Exception:  # noqa: BLE001
        zq = {}
    row = FyersPriceCheck(
        order_id=o.id,
        order_number=str(getattr(o, "order_number", "") or ""),
        user_id=o.user_id,
        user_code=str(getattr(user, "user_code", "") or ""),
        user_name=str(getattr(user, "full_name", "") or ""),
        token=str(inst.token),
        symbol=str(inst.symbol),
        exchange=_enum(inst.exchange),
        fyers_symbol=fyers_symbol,
        action=_enum(o.action),
        order_type=_enum(o.order_type),
        quantity=float(getattr(o, "quantity", 0) or 0),
        tick_size=_d128(_pos(getattr(inst, "tick_size", None))),
        zerodha_ltp=_d128(_pos(zq.get("ltp"))),
        zerodha_bid=_d128(_pos(zq.get("bid"))),
        zerodha_ask=_d128(_pos(zq.get("ask"))),
        compared_price=_d128(level),
        level_price=_d128(level),
        fyers_ltp=_d128(q.ltp),
        fyers_bid=_d128(q.bid),
        fyers_ask=_d128(q.ask),
        fyers_high=_d128(q.high),
        fyers_low=_d128(q.low),
        difference=_d128(past),
        status=PriceCheckStatus.MISSED_FILL,
        note=note,
        placed_at=now_utc(),
    )
    await row.insert()
    _reported.add((str(o.id), str(level)))
    logger.warning(
        "fyers_missed_fill order=%s symbol=%s %s %s level=%s fyers_ltp=%s",
        row.order_number, row.symbol, row.action, row.order_type, level, q.ltp,
    )
    # Same event as a price mismatch, so the super admin's toast and menu
    # badge cover it; `kind` picks the wording. No user details on the wire.
    await publish_admin_event(
        "price_mismatch",
        {"check_id": str(row.id), "symbol": row.symbol, "action": row.action, "kind": "missed_fill"},
    )


async def _quotes(symbols: list[str]) -> dict[str, fyers_service.FyersQuote]:
    out: dict[str, fyers_service.FyersQuote] = {}
    per = fyers_service.QUOTES_PER_CALL
    for i in range(0, min(len(symbols), per * MAX_CALLS_PER_SCAN), per):
        if not await fyers_price_check._rate_ok():
            logger.info("fyers_missed_fill_rate_limited")
            break
        try:
            out.update(await fyers_service.get_quotes(symbols[i:i + per]))
        except fyers_service.FyersUnavailableError as e:
            logger.info("fyers_missed_fill_quotes_unavailable: %s", e)
            break
    return out


async def scan_once() -> int:
    """One pass. Returns how many missed fills were recorded."""
    row = await fyers_service.get_settings()
    if not (row.enabled and row.is_connected and row.access_token):
        return 0
    orders = await Order.find(
        {"status": {"$in": _OPEN}, "order_type": {"$in": _RESTING}, "is_demo": {"$ne": True}}
    ).to_list()
    if not orders:
        return 0

    from app.services.matching_engine import resting_order_closed_gate

    closed = await resting_order_closed_gate(orders)
    sym_of: dict[str, str] = {}
    candidates: list[Any] = []
    for o in orders:
        try:
            level = _level(o)
            # Already reported at this level: don't spend a Fyers request on it.
            if closed(o) or level is None or await _already_reported(o, level):
                continue
            token = str(o.instrument.token)
            if token not in sym_of:
                sym, _ = await fyers_symbol_map.lookup(_enum(o.instrument.exchange), token)
                if not sym:
                    continue  # not a contract Fyers covers, or not in its list yet
                sym_of[token] = sym
            candidates.append(o)
        except Exception:  # noqa: BLE001 — one bad order must not stop the scan
            logger.exception("fyers_missed_fill_prepare_failed order=%s", getattr(o, "id", None))
    if not candidates:
        return 0

    quotes = await _quotes(sorted(set(sym_of.values())))
    hits: dict[str, tuple[Any, str, fyers_service.FyersQuote, Decimal, str]] = {}
    for o in candidates:
        sym = sym_of[str(o.instrument.token)]
        q = quotes.get(sym)
        if q is None:
            continue
        verdict = judge(o, q)
        if verdict is None:
            continue
        hits[str(o.id)] = (o, sym, q, *verdict)
    if not hits:
        return 0

    # Give the poller its moment, then report only what is still open at
    # the same level (a fill, cancel or modify in between clears it).
    await asyncio.sleep(GRACE_SEC)
    still = await Order.find(
        {"_id": {"$in": [h[0].id for h in hits.values()]}, "status": {"$in": _OPEN}}
    ).to_list()
    recorded = 0
    for fresh in still:
        o, sym, q, past, note = hits[str(fresh.id)]
        if _level(fresh) != _level(o):
            continue
        try:
            await _record(fresh, sym, q, past, note)
            recorded += 1
        except Exception:  # noqa: BLE001
            logger.exception("fyers_missed_fill_record_failed order=%s", fresh.id)
    return recorded


_running = False


async def missed_fill_loop(interval_sec: float = SCAN_INTERVAL_SEC) -> None:
    """Background loop launched from the lifespan (leader only)."""
    global _running
    if _running:
        return
    _running = True
    logger.info("fyers_missed_fill_loop_started", extra={"interval_sec": interval_sec})
    try:
        while _running:
            try:
                n = await scan_once()
                if n:
                    logger.info("fyers_missed_fills_recorded", extra={"count": n})
            except Exception:
                logger.exception("fyers_missed_fill_scan_failed")
            await asyncio.sleep(interval_sec)
    finally:
        _running = False


def stop_missed_fill_loop() -> None:
    global _running
    _running = False
