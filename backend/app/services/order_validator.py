"""Order pre-trade validator — 12 checks per spec, in order.

Returns (ok, applied_settings_snapshot) on success or raises OrderRejectedError.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from app.core.exceptions import (
    InsufficientFundsError,
    MarketClosedError,
    OrderRejectedError,
    SegmentNotAllowedError,
)
from app.models._base import (
    OrderAction,
    OrderType,
    ProductType,
)
from app.models.holiday import TradingHoliday
from app.models.instrument import Instrument
from app.models.position import Position, PositionStatus, UserPositionTracker
from app.models.user import User, UserStatus
from app.services import market_data_service, netting_service, wallet_router, wallet_service
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import is_weekend, now_ist, parse_hhmm, to_ist

# Exchanges that publish a daily circuit (price band). Infoway-fed international
# markets (crypto / forex / metals) have none, so we skip them.
_CIRCUIT_EXCHANGES = ("NSE", "BSE", "NFO", "BFO", "MCX", "CDS")

import re as _re

_MONTHS_RE = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"


def _strike_from_symbol(symbol: str | None) -> Decimal | None:
    """Best-effort strike from a MONTHLY option tradingsymbol
    (e.g. BANKNIFTY26JUL56700PE → 56700). Anchored on the 3-letter month so the
    strike digits are never confused with the numeric date. Weekly all-numeric
    symbols (NIFTY2670724800CE) intentionally return None — their strike is
    resolved from the authoritative Zerodha CSV (backfill), never guessed here.
    Used ONLY as a fallback when an option Instrument doc has a NULL strike so a
    valid sell isn't wrongly rejected."""
    if not symbol:
        return None
    m = _re.search(rf"(?:{_MONTHS_RE})(\d+)(?:CE|PE)$", symbol.strip().upper())
    if not m:
        return None
    try:
        v = to_decimal(m.group(1))
        return v if v > 0 else None
    except Exception:
        return None


async def _open_notional_for_kind(user_id: Any, wallet_kind: str) -> Decimal:
    """Σ |quantity| × current price over every OPEN position that trades from
    the given wallet kind (NSE_BSE / MCX / …). This is the aggregate NOTIONAL
    the portfolio-leverage cap bounds — deliberately NOT the wallet's
    `used_margin`, because margin is notional ÷ each leg's OWN leverage and so
    a 50× leg and a 33× leg with the same margin carry very different exposure;
    summing margin could never detect blended over-leverage. Uses each
    position's live `ltp` (the risk loop refreshes it) and falls back to
    `avg_price`, so the total tracks current market exposure the same way the
    Positions screen adds it up."""
    from beanie.operators import In

    from app.services import wallet_kinds as _wk_mod

    segs = _wk_mod.segments_for_kind(wallet_kind)
    if not segs:
        return Decimal("0")
    rows = await Position.find(
        Position.user_id == user_id,
        Position.status == PositionStatus.OPEN,
        In(Position.segment_type, segs),
    ).to_list()
    total = Decimal("0")
    for p in rows:
        qty = abs(to_decimal(p.quantity))
        if qty <= 0:
            continue
        px = to_decimal(p.ltp)
        if px <= 0:
            px = to_decimal(p.avg_price)
        total += qty * px
    return total


def _underlying_root(symbol: str | None) -> str:
    """Underlying root of an option tradingsymbol — everything before the first
    digit. NIFTY2681124900CE → NIFTY, CRUDEOIL25AUG5800CE → CRUDEOIL."""
    s = (symbol or "").upper().replace(" ", "")
    for i, ch in enumerate(s):
        if ch.isdigit():
            return s[:i]
    return s


def resting_side_error(
    order_type, action, price, trigger_price, market
) -> str | None:
    """Message when a resting order is priced on the side that fills instantly.

    A resting order is meant to WAIT. Put it on the wrong side of the market
    and its trigger is already true, so the poller fires it on the next 1.5 s
    pass — and because a LIMIT books at the price the USER typed, not at the
    market, the fill lands WORSE than the live quote. A BUY LIMIT at 8400 with
    the market at 8366 filled instantly at 8400: 34 points × 100 qty = 3,400
    handed away the moment it was placed.

        LIMIT BUY   fills on `ltp <= limit`   -> must be BELOW  market
        LIMIT SELL  fills on `ltp >= limit`   -> must be ABOVE  market
        SL-M  BUY   fires on `ltp >= trigger` -> must be ABOVE  market
        SL-M  SELL  fires on `ltp <= trigger` -> must be BELOW  market

    LIMIT and SL-M are mirror images: LIMIT rests for a pullback, SL-M rests
    for a breakout. Both are guarded, or a user dodges the block by switching
    order type.

    Returns None when it cannot tell (no market price, MARKET order, no price
    entered) — never block on a missing quote.
    """
    if market is None or market <= 0:
        return None

    if order_type == OrderType.LIMIT:
        p = price
        if p is None or p <= 0:
            return None
        if action == OrderAction.BUY and p >= market:
            return (
                f"A buy limit must be BELOW the current price 🪙{market}. "
                f"🪙{p} would fill immediately at your own price, not the market's. "
                f"Use Market to buy now, or SL-M to buy on a break above 🪙{market}."
            )
        if action == OrderAction.SELL and p <= market:
            return (
                f"A sell limit must be ABOVE the current price 🪙{market}. "
                f"🪙{p} would fill immediately at your own price, not the market's. "
                f"Use Market to sell now, or SL-M to sell on a break below 🪙{market}."
            )
        return None

    if order_type == OrderType.SL_M:
        t = trigger_price
        if t is None or t <= 0:
            return None
        if action == OrderAction.BUY and t <= market:
            return (
                f"A buy SL-M trigger must be ABOVE the current price 🪙{market} — "
                f"it is meant to fire on a break upward. 🪙{t} is already through, "
                f"so it would fire at once."
            )
        if action == OrderAction.SELL and t >= market:
            return (
                f"A sell SL-M trigger must be BELOW the current price 🪙{market} — "
                f"it is meant to fire on a break downward. 🪙{t} is already through, "
                f"so it would fire at once."
            )
    return None


async def day_range_block_for_bracket(
    user_id, instrument, segment_type: str, *, sl=None, tp=None
) -> str | None:
    """Error message when an SL/TP leg sits inside today's traded range, else
    None. Used by the SL/TP edit endpoints so a bracket cannot be parked
    somewhere the order gate would have refused.

    Reads the SAME `block_inside_day_range` toggle and the SAME
    `day_range_block` comparison as order placement, so the two can never
    disagree about what "inside the range" means.

    Fails OPEN on any missing piece — an unresolvable range or a settings
    hiccup must never leave a trader unable to move their stop.
    """
    from app.services import market_data_service, netting_service

    try:
        resolved = await netting_service.get_effective_settings(
            user_id, segment_type, action="BUY", product_type="NRML",
            symbol=getattr(instrument, "symbol", None),
        )
        if not bool((resolved.get("settings") or {}).get("block_inside_day_range")):
            return None
        q = await market_data_service.get_quote(instrument.token)
        hi, lo = to_decimal(q.get("high") or 0), to_decimal(q.get("low") or 0)
    except Exception:  # noqa: BLE001
        return None

    for label, raw in (("Stop loss", sl), ("Target", tp)):
        if raw in (None, "", 0, "0"):
            continue
        try:
            v = to_decimal(raw)
        except Exception:  # noqa: BLE001
            continue
        if day_range_block(v, None, hi, lo) is not None:
            return (
                f"{label} 🪙{v} is inside today's range (🪙{lo} – 🪙{hi}). "
                f"This segment only accepts levels above the high or below the low."
            )
    return None


def day_range_block(
    price: Decimal | None,
    trigger_price: Decimal | None,
    day_high: Decimal,
    day_low: Decimal,
) -> tuple[str, Decimal] | None:
    """(field, price) for the first price sitting INSIDE today's traded range.

    None = nothing to block, which is also the answer whenever the range is
    unknown. `day_high`/`day_low` of 0 mean pre-open, a fresh subscribe, or a
    quote with no OHLC — standing aside there is deliberate, because treating
    an unknown range as "everything is inside it" would reject every parked
    order before the bell.

    Bounds are INCLUSIVE: an order resting exactly ON the high or the low is
    still inside the band the instrument has already traded through today.

    BOTH prices are checked. An SL-M carries `price = 0` and sets only the
    trigger, so checking the limit price alone would let every SL-M through.
    """
    if not (day_high > 0 and day_low > 0 and day_high >= day_low):
        return None
    for field, candidate in (("Limit price", price), ("Trigger price", trigger_price)):
        if candidate is None or candidate <= 0:
            continue
        if day_low <= candidate <= day_high:
            return (field, candidate)
    return None


def option_underlying_key(instrument) -> str:
    """Option-chain underlying key for an option Instrument, derived from its
    tradingsymbol.

    Deliberately NOT `instrument.underlying_token`: that field is only ever
    populated by the seed and the Binance-options mirror, so every option
    auto-created from the Zerodha CSV carries NULL — and both strike gates
    that used to walk it were silently dead as a result.
    """
    from app.api.v1.user.option_chain import _norm_underlying

    return _norm_underlying(_underlying_root(getattr(instrument, "symbol", None)))


async def strike_window_breach(instrument, exchange_upper: str) -> int | None:
    """Window size N when this option's strike sits OUTSIDE the ATM ± N ladder
    the option chain exposes; None when it's inside (or undeterminable).

    Same three sources of truth the chain itself uses, so the two can never
    disagree: the cached Zerodha catalog for the strike ladder, the live
    underlying spot for the ATM anchor, and the super-admin's per-segment
    `strikes_around_atm`. The distance is measured in LADDER POSITIONS, not
    price arithmetic — NIFTY's ladder is 50-wide near ATM and 100-wide in the
    wings, so a fixed step size mis-measures it either way.

    Previously this walked `instrument.underlying_token`, which is only ever
    set by the seed and the Binance mirror — every option auto-created from
    the Zerodha CSV has it NULL, so the lookup returned None and the whole
    gate silently no-op'd. That is why a strike that had fallen out of the
    chain window (invisible in search AND in the picker) could still be
    added to from the Positions tab.

    Fails OPEN on every missing piece — a cold catalog or a momentary feed
    gap must never block a legitimate order.
    """
    # ponytail: reuses the option-chain's 5-min catalog cache. A COLD cache
    # makes the first option-open per underlying pay one full CSV scan
    # (~80k rows); the picker's 2 s poll keeps it warm in practice. If that
    # first-order latency ever shows up in `order_perf step=validate`, cache
    # the per-(underlying, expiry) strike ladder instead of the whole catalog.
    from app.api.v1.user.option_chain import allowed_strike_set

    allowed, window = await allowed_strike_set(
        option_underlying_key(instrument), getattr(instrument, "expiry", None), exchange_upper
    )
    if allowed is None:
        return None

    strike_val = float(to_decimal(instrument.strike))
    # Nearest-match rather than exact membership so float noise on the stored
    # strike can't wrongly reject; a strike genuinely off the ladder lands far
    # from every allowed value and is refused, which is the correct outcome.
    return None if any(abs(s - strike_val) < 0.001 for s in allowed) else window


async def _circuit_limits(instrument) -> tuple[Decimal | None, Decimal | None]:
    """(lower, upper) daily circuit band for the instrument, cached per-day in
    Redis (`circuit:{token}`, 12 h TTL). Sourced from the Zerodha quote's
    lower/upper_circuit_limit. Fail-open → (None, None) when the band isn't
    available, so a missing circuit NEVER blocks trading."""
    ex = str(getattr(instrument.exchange, "value", instrument.exchange) or "").upper()
    if ex not in _CIRCUIT_EXCHANGES:
        return (None, None)
    from app.core.redis_client import cache_get, cache_set

    token = str(instrument.token)
    ck = f"circuit:{token}"
    try:
        cached = await cache_get(ck)
        if isinstance(cached, dict):
            lc = to_decimal(cached.get("lc") or 0)
            uc = to_decimal(cached.get("uc") or 0)
            return (lc if lc > 0 else None, uc if uc > 0 else None)
    except Exception:
        pass
    try:
        from app.services.zerodha_service import zerodha

        key = f"{ex}:{instrument.symbol}"
        q = await zerodha.get_quote([key])
        row = (q or {}).get(key, {}) if isinstance(q, dict) else {}
        lc = to_decimal(row.get("lower_circuit_limit") or 0)
        uc = to_decimal(row.get("upper_circuit_limit") or 0)
        try:
            await cache_set(ck, {"lc": str(lc), "uc": str(uc)}, ttl_sec=43200)
        except Exception:
            pass
        return (lc if lc > 0 else None, uc if uc > 0 else None)
    except Exception:
        return (None, None)


@dataclass
class ValidatedOrder:
    settings: dict[str, Any]
    netting_settings: dict[str, Any]  # full netting resolved dict for matching engine
    margin_required: Decimal
    ltp: Decimal


def _money_to_float(v: Any) -> float:
    """Coerce ANY money-shaped value (Decimal128 / Decimal / str / number / None)
    into a Python float. Python's built-in ``float()`` does NOT accept
    ``bson.Decimal128`` and raises ``TypeError: float() argument must be a
    string or a real number, not 'Decimal128'`` — which is the exact error
    the user saw on SELL / reducing orders against an open Position. We
    route every money read in this validator through this helper so that
    bug can never resurface."""
    if v is None:
        return 0.0
    try:
        return float(to_decimal(v))
    except Exception:
        try:
            return float(str(v))
        except Exception:
            return 0.0


def bracket_direction_error(
    action: Any, ref_price: Any, sl: Any = None, tp: Any = None
) -> str | None:
    """User-facing message when an SL/TP leg is on the WRONG side of ref_price,
    else None.

    A leg placed on the profitable side is ALREADY "hit" the instant it's stored:
    the risk enforcer fires it immediately and the matching engine fills SL/TP at
    EXACTLY the leg price (a deliberate operator choice), booking a fill at a
    price the market never traded → fake P&L. So reject impossible legs up front.

    ref = live LTP (caller falls back to entry price). ref <= 0 → None (fail open;
    never block a trade just because the mark is momentarily unavailable).
      • BUY / long : SL must be < ref, TP must be > ref
      • SELL / short: SL must be > ref, TP must be < ref
    """
    ref = _money_to_float(ref_price)
    if ref <= 0:
        return None
    side = str(getattr(action, "value", action) or "").upper()
    is_long = side in ("BUY", "LONG")
    sl_f = _money_to_float(sl) if sl not in (None, "", 0, "0") else None
    tp_f = _money_to_float(tp) if tp not in (None, "", 0, "0") else None
    if is_long:
        if sl_f is not None and sl_f >= ref:
            return f"Stop Loss 🪙{sl_f:g} must be BELOW current price 🪙{ref:.2f} for a BUY position."
        if tp_f is not None and tp_f <= ref:
            return f"Target 🪙{tp_f:g} must be ABOVE current price 🪙{ref:.2f} for a BUY position."
    else:
        if sl_f is not None and sl_f <= ref:
            return f"Stop Loss 🪙{sl_f:g} must be ABOVE current price 🪙{ref:.2f} for a SELL position."
        if tp_f is not None and tp_f >= ref:
            return f"Target 🪙{tp_f:g} must be BELOW current price 🪙{ref:.2f} for a SELL position."
    return None


async def validate(
    *,
    user: User,
    instrument: Instrument,
    segment_type: str,
    action: OrderAction,
    order_type: OrderType,
    product_type: ProductType,
    lots: float,
    quantity: float,
    price: Decimal,
    trigger_price: Decimal,
    is_amo: bool,
    is_squareoff: bool = False,
    expected_price: Decimal | None = None,
    bracket_sl: Decimal | None = None,
    bracket_tp: Decimal | None = None,
) -> ValidatedOrder:
    # 12) user status
    if user.status != UserStatus.ACTIVE:
        raise OrderRejectedError("Account is not active", code="ACCOUNT_INACTIVE")
    if not user.permissions.can_place_orders:
        raise OrderRejectedError("Order placement disabled for this account", code="PERMISSION_DENIED")

    # ── Batch independent async lookups to cut latency ────────────
    # Risk, netting settings, position tracker, and open position are all
    # independent — fire them in parallel instead of sequentially.
    is_expiry_day_now = bool(instrument.expiry and instrument.expiry == now_ist().date())

    # Multi-wallet: overlay the per-wallet risk override for this order's
    # segment (None when the flag is off → legacy single-risk behaviour).
    _risk_kind = wallet_router.kind_for(segment_type) if wallet_router.enabled() else None

    async def _fetch_risk() -> dict[str, Any]:
        try:
            rp = await netting_service.get_effective_risk(str(user.id), _risk_kind)
            return rp.get("settings", {}) if rp else {}
        except Exception:
            return {}

    async def _fetch_netting() -> dict[str, Any]:
        return await netting_service.get_effective_settings(
            user.id,  # type: ignore[arg-type]
            segment_type,
            action=action.value if hasattr(action, "value") else str(action),
            option_type=instrument.option_type.value if instrument.option_type else None,
            product_type=product_type.value if hasattr(product_type, "value") else str(product_type),
            is_expiry_day=is_expiry_day_now,
            symbol=instrument.symbol,
        )

    import logging as _logging
    import time as _time

    _vlog = _logging.getLogger(__name__)
    _t0 = _time.perf_counter()
    risk, resolved, tracker, open_position, ltp = await asyncio.gather(
        _fetch_risk(),
        _fetch_netting(),
        UserPositionTracker.find_one(
            UserPositionTracker.user_id == user.id,
            UserPositionTracker.segment_type == segment_type,
            UserPositionTracker.instrument_token == instrument.token,
        ),
        # IMPORTANT: lookup keys must match the matching_engine's
        # `existing_pos` query (services/matching_engine.py) — they
        # work as a pair (validator caps the order, matching_engine
        # merges the fill into the same position row). Previously the
        # validator filtered by `segment_type` while the engine filtered
        # by `product_type`, so a position opened under an older
        # segment-name spelling (e.g. CRYPTO_PERPETUAL renamed to
        # CRYPTO) was invisible to the validator's `signed_held` /
        # `projected_net` calc — every follow-up order saw "no existing
        # position", passed the `max_each_lot` cap on its own lots, and
        # the engine merrily pyramided into the existing row. End-user
        # symptom: lots stop at the per-order cap but the position size
        # keeps climbing past `maxLots/script` (the user-reported "size
        # badhate ja raha hai" bug).
        Position.find_one(
            Position.user_id == user.id,
            Position.instrument.token == instrument.token,
            Position.product_type == product_type,
            Position.status == PositionStatus.OPEN,
        ),
        market_data_service.get_ltp(instrument.token),
    )
    _vlog.info(
        "order_perf step=validate.gather5 ms=%.1f",
        (_time.perf_counter() - _t0) * 1000,
    )
    s: dict[str, Any] = resolved["settings"]

    # 1) Block gate — split into two flags so closing trades survive a
    # paused segment:
    #   • `is_active = false`   → segment is turned OFF entirely. The
    #     user side hides instruments from search and we reject EVERY
    #     order (including squareoff) here as a belt-and-braces check.
    #   • `trading_enabled = false` → new entries are blocked but the
    #     user can still see prices and CLOSE existing positions. The
    #     `is_reducing` / `is_squareoff` exemption fires below once
    #     those values are computed.
    if not bool(s.get("is_active", True)):
        raise SegmentNotAllowedError(
            f"Segment {segment_type} is disabled — contact your broker"
        )

    lot_size = max(1, instrument.lot_size or 1)

    # 2) lot limits — admin's segment settings are the single source of truth.
    # Squareoff orders are EXEMPT from the min-lot floor: a legacy position
    # opened before the Infoway lot-size table existed may have stored
    # `quantity = 0.99` against `lot_size = 1`; once the canonical heal
    # rewrites lot_size to 100 (XAUUSD = 100 oz/lot), the close path
    # recomputes `lots = quantity / lot_size = 0.0099` which would
    # otherwise trip the 0.01 minimum and leave the trader unable to
    # exit. Same exemption applies to admin-initiated force-closes
    # (kill switch, risk auto-flatten, EOD rollover) which all set
    # `is_squareoff=True`.
    min_lot = float(s.get("min_lot") or 1)
    order_lot = float(s.get("order_lot") or 0)  # per-order maximum (new positions only)
    if lots < min_lot and not is_squareoff:
        raise OrderRejectedError(f"Minimum {min_lot} lot(s) required", code="LOT_BELOW_MIN")

    # 3) position limits — running total per instrument + per segment
    #
    # `Position.quantity` is stored in CONTRACTS (lots × lot_size), while
    # the admin's caps and the user's `lots` field are in LOTS. Mixing
    # the two units meant a 1-lot follow-up on a NIFTY long (75 contracts
    # held) computed `projected_net = 75 + 1 = 76` and tripped the
    # 100-lot per-instrument cap as if the user already held 75 lots.
    # Convert to lots up-front so every downstream check (`is_reducing`,
    # `MAX_EACH_EXCEEDED`) compares apples to apples. We divide by the
    # POSITION's own stored lot_size (not the live instrument's) so a
    # legacy row where lot_size has since been corrected by the canonical
    # table still resolves to the same lot count it was opened with.
    held = tracker.total_lots if tracker else 0
    pos_lot_size = max(
        1,
        int(
            (getattr(open_position.instrument, "lot_size", 0) or lot_size)
            if open_position
            else lot_size
        ),
    )
    signed_held = (
        float(open_position.quantity) / pos_lot_size if open_position else 0.0
    )  # IN LOTS (signed: + long, − short, 0 flat)
    delta = float(lots) if action == OrderAction.BUY else -float(lots)
    projected_net = signed_held + delta
    is_reducing = abs(projected_net) < abs(signed_held)  # closing / partial close

    # ── Square-off / Exit must be REDUCE-ONLY ──────────────────────────
    # An Exit / square-off order exists only to FLATTEN existing exposure.
    # If there is NO open position, or the order is on the SAME side as the
    # held position (which would ADD to it), executing it opens / increases
    # a brand-new position — never what "Exit" means.
    #
    # Production incident CL66147834 (2026-06-24): user tapped Exit, the
    # long closed (SELL sq=true), then a slow-UI second Exit ~25 s later —
    # PAST the /squareoff endpoint's 10 s single-flight lock — landed as a
    # fresh SELL and opened an unwanted SHORT, which then had to be bought
    # back. Rejecting any non-closing square-off makes a duplicate / stale /
    # late Exit a safe no-op regardless of which path it arrives on.
    #
    # We deliberately gate on "no position / wrong side" rather than on
    # MAGNITUDE, so float lot-rounding on a legitimate FULL close can never
    # wrongly block a user from exiting. All system closers (risk enforcer,
    # admin force-close, EOD rollover, kill-switch) always send the correct
    # opposite side against a live open position, so they pass untouched.
    if is_squareoff:
        squareoff_adds_or_absent = (
            signed_held == 0 or (signed_held > 0) == (delta > 0)
        )
        if squareoff_adds_or_absent:
            raise OrderRejectedError(
                "No open position to close — square-off is reduce-only",
                code="SQUAREOFF_NO_POSITION",
            )

    # Per-order cap: only applies to NEW/opening orders — closing must always
    # be allowed in full so user can exit the entire position in one click.
    if not is_squareoff and not is_reducing and order_lot > 0 and lots > order_lot:
        raise OrderRejectedError(
            f"Maximum {order_lot} lot(s) per order", code="LOT_PER_ORDER_MAX"
        )

    # ── Risk: exit-only mode ───────────────────────────────────────
    # Admin freezes the account for new entries (e.g. during volatility,
    # margin warnings). Only reducing/closing trades remain allowed.
    if risk.get("exitOnlyMode") and not is_reducing:
        raise OrderRejectedError(
            "Exit-only mode is active — only closing trades are allowed",
            code="EXIT_ONLY_MODE",
        )

    # ── Banned security (super-admin) — CLOSE-ONLY ─────────────────
    # A super-admin can ban a stock (globally or for one admin's users). A
    # banned instrument allows only reducing / squaring off an existing
    # position — no new or adding entry. (The open position's P&L is frozen
    # separately in refresh_unrealized_pnl.)
    if not is_reducing and not is_squareoff:
        from app.services import banned_security_service

        if await banned_security_service.is_banned(user, str(instrument.token)):
            raise OrderRejectedError(
                "This security is banned — only closing trades are allowed",
                code="SECURITY_BANNED",
            )

    # ── Settlement-pending gate ────────────────────────────────────
    # When `User.auto_settlement == False` and a debit has left the
    # wallet's available_balance below 0, `wallet_service` queues a
    # PENDING SettlementRequest. While that row exists the user is
    # blocked from new OPENING trades — only `is_reducing` (closing /
    # partial close) or `is_squareoff` (admin / risk auto-flatten)
    # orders pass through, mirroring the exit-only-mode exemption
    # pattern just above. Admin clears the block by approving the
    # request from Payments → Settlement Requests.
    if not is_reducing and not is_squareoff:
        try:
            from app.services import wallet_service as _ws

            if await _ws.has_pending_settlement_request(user.id):
                raise OrderRejectedError(
                    "Settlement pending — close existing positions or "
                    "wait for admin approval before opening new trades",
                    code="SETTLEMENT_PENDING",
                )
        except OrderRejectedError:
            raise
        except Exception:  # pragma: no cover
            # A Mongo hiccup on the probe must NOT block legitimate
            # orders. Fail-open is acceptable here because the
            # downstream `wallet_service.adjust` will still gate via
            # InsufficientFundsError if margin can't be sourced.
            pass

    # ── Block gate (segment level): tradingEnabled = false ────────
    # Admin paused this segment. Existing positions can still be closed
    # (the user can exit their book) but no new entries are allowed.
    # `is_squareoff` covers admin-initiated kill-switch / risk auto-flatten
    # so those always pass through.
    if not bool(s.get("trading_enabled", True)) and not is_reducing and not is_squareoff:
        raise SegmentNotAllowedError(
            f"Segment {segment_type} is paused — only closing trades are allowed",
        )

    # ── Expiry-day hold timer ─────────────────────────────────────
    # Admin can force users to hold profitable / losing trades for a
    # minimum number of seconds on expiry day before allowing close.
    # The check fires only when:
    #   • This is a CLOSING order (`is_reducing`) and not an admin-driven
    #     squareoff (kill-switch / risk auto-flatten / EOD rollover are
    #     never gated by the user-facing hold timer).
    #   • The instrument expires today (matches the same predicate the
    #     resolver uses).
    #   • An open position exists with an `opened_at` timestamp we can
    #     compare against.
    # Zero means "no minimum" — opt out per segment.
    if (
        is_reducing
        and not is_squareoff
        and is_expiry_day_now
        and open_position is not None
        and getattr(open_position, "opened_at", None) is not None
    ):
        from app.utils.time_utils import now_utc

        try:
            held_sec = (now_utc() - open_position.opened_at).total_seconds()
            # Sign of the current position tells us whether the user is
            # closing a long (cur_qty > 0, P/L = ltp − avg) or a short
            # (cur_qty < 0, P/L = avg − ltp). Every money read uses
            # `_money_to_float` so a Decimal128 / Decimal / str payload
            # all coerce cleanly — the soft hold-timer must never crash
            # the entire order pipeline.
            avg = _money_to_float(getattr(open_position, "avg_price", 0))
            ltp_f = _money_to_float(ltp)
            qty_f = float(open_position.quantity or 0)
            if avg > 0 and ltp_f > 0:
                unrealized = (ltp_f - avg) if qty_f > 0 else (avg - ltp_f)
                min_hold = float(
                    s.get("expiry_profit_hold") if unrealized >= 0 else s.get("expiry_loss_holding")
                    or 0
                )
                if min_hold > 0 and held_sec < min_hold:
                    kind = "profit" if unrealized >= 0 else "loss"
                    raise OrderRejectedError(
                        f"Expiry-day {kind}-hold: this position must be held for "
                        f"{int(min_hold)} s before closing (held {int(held_sec)} s)",
                        code=f"EXPIRY_{kind.upper()}_HOLD",
                    )
        except OrderRejectedError:
            # Hold-timer rejection is a legitimate user-facing error —
            # bubble it through. Other exceptions are swallowed below.
            raise
        except Exception:
            _vlog.warning("expiry_hold_check_failed", exc_info=True)

    # ── Always-on hold timer (Risk Management settings) ─────────────
    # The two `*TradeHoldMinSeconds` knobs on the Risk Management page
    # apply to every user-initiated close, every day — not just expiry.
    # Admin uses these to prevent scalping (positive hold) or panic
    # closing (loss hold). Same exemptions as the expiry-day version
    # above: only fires on user-driven reductions, never on admin
    # squareoff. Zero = feature off.
    if (
        is_reducing
        and not is_squareoff
        and open_position is not None
        and getattr(open_position, "opened_at", None) is not None
    ):
        from app.utils.time_utils import now_utc

        try:
            held_sec_rs = (now_utc() - open_position.opened_at).total_seconds()
            avg_rs = _money_to_float(getattr(open_position, "avg_price", 0))
            ltp_rs = _money_to_float(ltp)
            qty_rs = float(open_position.quantity or 0)
            if avg_rs > 0 and ltp_rs > 0:
                unrealized_rs = (ltp_rs - avg_rs) if qty_rs > 0 else (avg_rs - ltp_rs)
                min_hold_rs = float(
                    (risk.get("profitTradeHoldMinSeconds") if unrealized_rs >= 0 else risk.get("lossTradeHoldMinSeconds"))
                    or 0
                )
                if min_hold_rs > 0 and held_sec_rs < min_hold_rs:
                    kind = "profit" if unrealized_rs >= 0 else "loss"
                    raise OrderRejectedError(
                        f"{kind.capitalize()} trade must be held for "
                        f"{int(min_hold_rs)} s before close (held {int(held_sec_rs)} s)",
                        code=f"{kind.upper()}_HOLD",
                    )
        except OrderRejectedError:
            raise
        except Exception:
            _vlog.warning("trade_hold_check_failed", exc_info=True)

    intra_limit = int(s.get("intraday_lot_limit") or 0)
    hold_limit = int(s.get("holding_lot_limit") or 0)
    max_each = int(s.get("max_each_lot") or 0)

    # Cap only applies when the order would INCREASE exposure on this script.
    # A risk/admin auto-flatten (`is_squareoff`) is ALWAYS an exit — it must
    # never be blocked by a position-size cap, or the stop-out can't fire and
    # the risk_enforcer hot-loops retrying it every 250 ms (observed in prod:
    # a 584-lot position stuck, "Per-instrument cap reached: would hold 584.1
    # > 10" spamming the logs + loading the backend while never flattening).
    # The exit gates above already exempt is_squareoff; these three position-
    # size caps were missing that same exemption.
    if max_each and not is_reducing and not is_squareoff and abs(projected_net) > max_each:
        raise OrderRejectedError(
            f"Per-instrument cap reached: would hold {abs(projected_net)} > {max_each}",
            code="MAX_EACH_EXCEEDED",
        )
    if (
        not is_reducing
        and not is_squareoff
        and product_type == ProductType.MIS
        and intra_limit
        and (tracker.intraday_lots if tracker else 0) + lots > intra_limit
    ):
        raise OrderRejectedError(f"Intraday lot limit {intra_limit} reached", code="INTRADAY_LIMIT")
    if (
        not is_reducing
        and not is_squareoff
        and product_type in (ProductType.NRML, ProductType.CNC)
        and hold_limit
        and (tracker.holding_lots if tracker else 0) + lots > hold_limit
    ):
        raise OrderRejectedError(f"Holding lot limit {hold_limit} reached", code="HOLDING_LIMIT")

    # ── 4) Bracket SL / TP directional sanity ──────────────────────
    # Without this, a user could type TP=95 on a LONG at 100 and the risk-enforcer
    # would immediately square-off the position the moment the order fills
    # because the trigger condition `ltp >= tp` would be true on every
    # tick. Same for SL on the wrong side: trigger condition becomes
    # impossible and the bracket never fires. The check uses the entry
    # price the order is actually going to land at:
    #   • LIMIT / SL-M → user-entered price / trigger.
    #   • MARKET       → live close-side quote (ask for BUY, bid for SELL),
    #                    falling back to LTP.
    # The "Max % away from market" band (limitAwayPercent) used to sit here.
    # Removed on operator instruction: it rejected any resting order near the
    # market, and once the day-range gate shipped the two bands could contradict
    # each other outright — a range wider than the % band left NO price that
    # satisfied both. The day-range gate below is the surviving control.
    #
    # It also carried the SL/TP MINIMUM-distance rule off the same number, so
    # that went with it: brackets may now sit as close to entry as the trader
    # likes. `bracket_direction_error` still blocks a leg on the WRONG SIDE.

    # ── Resting order must be on the WAITING side of the market ────────
    # A LIMIT/SL-M priced through the market has its trigger already true, so
    # the poller fires it on the next pass — and a LIMIT books at the price the
    # USER typed, so the fill lands worse than the live quote. Reject it with a
    # message that names the right tool instead of silently taking the bad fill.
    #
    # Exits are exempt, like every other opening-side gate: a close must never
    # be blocked, or the stop-out engine retries it forever.
    if (
        order_type != OrderType.MARKET
        and not is_squareoff
        and not is_reducing
    ):
        _rs_ref = None
        try:
            _rq = await market_data_service.get_quote(instrument.token)
            # Use the side the order would actually transact against; fall back
            # to LTP when the book is thin or off-hours.
            _raw = _rq.get("ask") if action == OrderAction.BUY else _rq.get("bid")
            _rs_ref = to_decimal(_raw) if _raw not in (None, 0, "0") else None
        except Exception:  # noqa: BLE001
            _rs_ref = None
        if _rs_ref is None or _rs_ref <= 0:
            _rs_ref = ltp if ltp and ltp > 0 else None

        _rs_msg = resting_side_error(order_type, action, price, trigger_price, _rs_ref)
        if _rs_msg:
            raise OrderRejectedError(_rs_msg, code="RESTING_WRONG_SIDE")

    # ── Block parked orders INSIDE today's traded range ────────────────
    # Admin toggle, per segment, default OFF. A resting order priced between
    # today's low and high fills on the next small wobble instead of a real
    # breakout — a cheap/phantom fill. With this on, a parked order must sit
    # ABOVE the day's high or BELOW its low, so it can only trigger on a
    # genuine new extreme.
    #
    #
    # EXEMPTIONS, each one deliberate:
    #   • MARKET orders — they fill on touch, they never rest, so "inside the
    #     range" is meaningless for them.
    #   • squareoff / reducing — an EXIT must never be blocked. The stop-out
    #     engine retries a rejected close forever, so blocking one here would
    #     hot-loop and the position would never flatten.
    #   • unknown range — pre-open, a fresh subscribe, or any quote without
    #     OHLC yields high/low of 0. Stand aside rather than reject: an
    #     unknown range must not block every order before the bell.
    if (
        bool(s.get("block_inside_day_range"))
        and order_type != OrderType.MARKET
        and not is_squareoff
        and not is_reducing
    ):
        try:
            _dq = await market_data_service.get_quote(instrument.token)
            _day_high = to_decimal(_dq.get("high") or 0)
            _day_low = to_decimal(_dq.get("low") or 0)
        except Exception:  # noqa: BLE001 — a quote hiccup must not block a trade
            _day_high = _day_low = to_decimal(0)

        # Both bounds must be real AND sane; a half-populated OHLC tells us
        # nothing about the range.
        hit = day_range_block(price, trigger_price, _day_high, _day_low)
        if hit is not None:
            field, candidate = hit
            raise OrderRejectedError(
                f"{field} 🪙{candidate} is inside today's range "
                f"(🪙{_day_low} – 🪙{_day_high}). This segment only accepts "
                f"orders above the high or below the low.",
                code="INSIDE_DAY_RANGE",
            )

    # SL / TP directional check — simple, always-on guard.
    # BUY:  SL must be below entry, TP must be above entry.
    # SELL: SL must be above entry, TP must be below entry.
    # Reference is the user's limit price for LIMIT orders, LTP for MARKET.
    _dir_ref = price if (order_type != OrderType.MARKET and price and price > 0) else ltp
    if _dir_ref and _dir_ref > 0:
        if bracket_sl is not None and bracket_sl > 0:
            if action == OrderAction.BUY and bracket_sl >= _dir_ref:
                raise OrderRejectedError(
                    f"Stop Loss 🪙{bracket_sl} must be BELOW entry 🪙{_dir_ref} for a BUY order.",
                    code="SL_WRONG_SIDE",
                )
            if action == OrderAction.SELL and bracket_sl <= _dir_ref:
                raise OrderRejectedError(
                    f"Stop Loss 🪙{bracket_sl} must be ABOVE entry 🪙{_dir_ref} for a SELL order.",
                    code="SL_WRONG_SIDE",
                )
        if bracket_tp is not None and bracket_tp > 0:
            if action == OrderAction.BUY and bracket_tp <= _dir_ref:
                raise OrderRejectedError(
                    f"Target 🪙{bracket_tp} must be ABOVE entry 🪙{_dir_ref} for a BUY order.",
                    code="TP_WRONG_SIDE",
                )
            if action == OrderAction.SELL and bracket_tp >= _dir_ref:
                raise OrderRejectedError(
                    f"Target 🪙{bracket_tp} must be BELOW entry 🪙{_dir_ref} for a SELL order.",
                    code="TP_WRONG_SIDE",
                )

    # Hard-cap: reject LIMIT prices > 50% away from LTP regardless of
    # 50%-from-LTP hard cap. Prevents phantom fills caused by typos
    # or a momentarily zero/stale LTP from triggering 90%-off orders.
    _MAX_LIMIT_DEV_PCT = to_decimal("50")
    if ltp and ltp > 0 and order_type != OrderType.MARKET:

        def _hard_cap_check(cap_name: str, candidate: Decimal | None) -> None:
            if candidate is None or candidate <= 0:
                return
            dev = abs(candidate - ltp) / ltp * 100
            if dev > _MAX_LIMIT_DEV_PCT:
                raise OrderRejectedError(
                    f"{cap_name} 🪙{candidate} deviates {dev:.1f}% from current market "
                    f"🪙{ltp}. Maximum allowed deviation is {_MAX_LIMIT_DEV_PCT}%.",
                    code=f"{cap_name.upper().replace(' ', '_')}_TOO_FAR",
                )

        _hard_cap_check("limit price", price)
        _hard_cap_check("trigger price", trigger_price)

    # Crypto options don't follow the equity/index ATM-step model (spot in the
    # tens of thousands, arbitrary strike ladders), so the ATM strike-distance
    # gates below (#5 strike-step, #6d strike-far-percent) misfire. Skip them
    # for crypto — detected via segment name or the instrument's exchange.
    _exch_upper = str(getattr(instrument.exchange, "value", instrument.exchange) or "").upper()
    _is_crypto = "CRYPTO" in segment_type.upper() or _exch_upper == "CRYPTO"

    # 5) ATM strike WINDOW (option segments) — dynamic, spot-anchored.
    #    Tradeable strikes = ATM ± `strikes_around_atm` (the SAME window the
    #    option chain shows). A strike outside the window can only be SQUARED
    #    OFF (close existing) — NOT opened/added — so when the market moves and
    #    a strike falls out of the window, the user's position becomes close-only
    #    (like a banned security), exactly the real-broker behaviour requested.
    #    Skipped for squareoff / reducing orders so an out-of-window position can
    #    always be exited.
    if (
        instrument.strike is not None
        and "OPTION" in segment_type.upper()
        and not _is_crypto
        and not is_squareoff
        and not is_reducing
    ):
        _window = await strike_window_breach(instrument, _exch_upper)
        if _window is not None:
            raise OrderRejectedError(
                f"Strike is outside the tradeable window (ATM ±{_window} strikes). "
                f"You can only square off this strike, not add to it.",
                code="STRIKE_OUT_OF_RANGE",
            )

    # 6) OTM extra-strict cap
    # Skipped for closing / squareoff orders — those REDUCE existing
    # exposure, they don't add a new OTM bet. Risk auto-squareoff on
    # a stop-out used to silently fail in an infinite retry loop here
    # ("OTM cap 5 reached") because the user already had > otm_max
    # lots open and the enforcer kept trying to add more by routing
    # the close as a regular fill. Same exemption every other lot/qty
    # cap above already gives via `is_squareoff` / `is_reducing`.
    otm_max = int(s.get("otm_max_each_lot") or 0)
    if (
        otm_max
        and "OPTION" in segment_type.upper()
        and instrument.option_type
        and not is_squareoff
        and not is_reducing
    ):
        # Heuristic: rely on max_each_lot already handling general cap; here we tighten
        if (held + lots) > otm_max:
            raise OrderRejectedError(f"OTM cap {otm_max} reached", code="OTM_CAP_EXCEEDED")

    # 6a-i) minimum quantity check (equity segments that use qty instead of lots)
    min_qty = float(s.get("min_qty") or 0)
    if min_qty > 0 and quantity < min_qty:
        raise OrderRejectedError(
            f"Minimum quantity is {min_qty}, got {quantity}",
            code="QTY_BELOW_MIN",
        )

    # 6a) per-order quantity cap (relevant mostly for equity segments).
    # Skip for reducing/closing orders — those exit existing exposure.
    per_order_qty = float(s.get("per_order_qty") or 0)
    if not is_reducing and per_order_qty > 0 and quantity > per_order_qty:
        raise OrderRejectedError(
            f"Quantity {quantity} exceeds per-order cap of {per_order_qty}",
            code="QTY_PER_ORDER_EXCEEDED",
        )

    # 6b) running total quantity per script (running held + new ≤ cap)
    max_qty_script = float(s.get("max_qty_per_script") or 0)
    if not is_reducing and max_qty_script > 0:
        held_qty = (tracker.total_lots if tracker else 0) * lot_size
        if held_qty + quantity > max_qty_script:
            raise OrderRejectedError(
                f"Per-script quantity cap {max_qty_script} would be breached "
                f"(held {held_qty} + new {quantity})",
                code="MAX_QTY_PER_SCRIPT",
            )

    # 6c) per-order notional cap (🪙 value) — skip for closing orders
    max_value = float(s.get("max_value") or 0)
    if not is_reducing and max_value > 0:
        ref_price_for_value = price if price > 0 else ltp
        notional_check = quantity * float(ref_price_for_value)
        if notional_check > max_value:
            raise OrderRejectedError(
                f"Order value 🪙{notional_check:,.0f} exceeds per-order cap of 🪙{max_value:,.0f}",
                code="MAX_VALUE_EXCEEDED",
            )

    # 6d) Option-leg strike-distance from spot. Single percent cap from
    # admin's Options column — same value gates both BUY and SELL legs.
    # The option-chain dialog filters the same way (strikes outside this
    # band aren't shown to the user) so anything that reaches this check
    # is the result of a deliberate token-paste, not normal click flow.
    # Skipped for closing / squareoff, same as every other opening-side cap —
    # a position whose strike drifted past the cap must always stay exitable.
    far_pct = float(s.get("strike_far_percent") or 0)
    if (
        far_pct > 0
        and "OPTION" in segment_type.upper()
        and instrument.strike is not None
        and not _is_crypto
        and not is_squareoff
        and not is_reducing
    ):
        from app.api.v1.user.option_chain import _underlying_spot

        spot = float(await _underlying_spot(option_underlying_key(instrument)) or 0)
        if spot > 0:
            strike_val = float(to_decimal(instrument.strike))
            deviation_pct = abs(strike_val - spot) / spot * 100
            if deviation_pct > far_pct:
                raise OrderRejectedError(
                    f"Strike {strike_val:.0f} is {deviation_pct:.1f}% from spot {spot:.2f} "
                    f"— cap is {far_pct:.1f}%",
                    code="STRIKE_FAR_CAP",
                )

    # 7) overnight selling
    if not s.get("selling_overnight", True) and action == OrderAction.SELL and product_type != ProductType.MIS:
        # Only block if user has no current long position to cover
        if not tracker or tracker.holding_lots <= 0:
            raise OrderRejectedError(
                "Overnight short selling is disabled for your account", code="NO_OVERNIGHT_SHORT"
            )

    # 8) expiry-day rules
    # Two knobs on the segment matrix drive this:
    #   • `expiry_intraday_margin` (and the OPTION-buy/sell variants
    #     picked earlier in the resolver) → the value to use today.
    #   • `expiry_margin_as_percent` → when False the value above is a
    #     flat 🪙/lot (mirrors `margin_calc_mode = fixed`); when True
    #     it's % of notional / a leverage multiplier (interpretation
    #     follows the segment's `margin_calc_mode`). Lets admin run
    #     normal trading on, say, Times-leverage and still impose a
    #     punitive flat 🪙 on expiry.
    # Use `effective_expiry` so instruments whose stored `expiry` is None
    # (data-quality gap from Zerodha sync) still get the expiry-day rule
    # applied based on a symbol-derived fallback date. Without this,
    # rows like CRUDEOIL26JULFUT with a null `expiry` skipped the rule
    # entirely and traded at the regular tier on their actual expiry day.
    from app.services.instrument_service import effective_expiry as _effective_expiry

    _expiry = _effective_expiry(instrument)
    is_expiry_today = bool(_expiry and _expiry == now_ist().date())
    if is_expiry_today:
        expiry_as_percent = bool(s.get("expiry_margin_as_percent", True))
        seg_mode = (s.get("margin_calc_mode") or "").lower()
        # Expiry-day margin tier. When the admin did NOT set an explicit
        # `expiry_intraday_margin`, fall back to the NORMAL tier — for a Times
        # segment that's `leverage` (e.g. 500×), NOT `margin_percentage` (which
        # is 100 in Times mode and would silently cut a 500× instrument to 100×
        # on its expiry day, so the same lot suddenly demanded 5× the margin and
        # the order failed with InsufficientFunds — the exact MCX GOLD bug).
        _exp_explicit = s.get("expiry_intraday_margin")
        if _exp_explicit:
            expiry_margin = float(_exp_explicit)
        elif seg_mode == "times":
            expiry_margin = float(s.get("leverage") or 100.0)
        else:
            expiry_margin = float(s.get("margin_percentage") or s.get("leverage") or 100.0)
        if not expiry_as_percent:
            # Admin explicitly opted for flat 🪙/lot on expiry — switch
            # the calc into fixed mode regardless of segment-default mode.
            s["margin_calc_mode"] = "fixed"
            s["fixed_margin_per_lot"] = expiry_margin
            s["margin_percentage"] = 0.0
            s["leverage"] = 1.0
        elif seg_mode == "times":
            # Times segment + percent expiry knob → admin's number is a
            # LEVERAGE multiplier, same units as `intradayMargin` in Times
            # mode (e.g. 500 means 500×). Previously the code force-set
            # `leverage = 1` and stuffed the multiplier into
            # `margin_percentage`, which turned a 500× setting into "500%
            # of notional × ÷ 1" — i.e. 5× the notional locked. On a
            # 🪙10L crude lot that was 🪙51L margin required and every
            # expiry-day order failed with InsufficientFunds. Now we
            # preserve the Times semantics so the user pays the same
            # margin tier on expiry day unless admin explicitly changed
            # `expiryDayIntradayMargin` to a stricter value.
            s["leverage"] = max(1.0, expiry_margin)
            s["margin_percentage"] = 100.0
            s["fixed_margin_per_lot"] = 0.0
        elif seg_mode == "fixed":
            # Fixed segment + percent expiry knob → ambiguous (admin
            # chose Fixed 🪙/lot but didn't flip the `as_percent` flag).
            # Honour the existing fixed semantics: the expiry value is
            # 🪙/lot.
            s["margin_calc_mode"] = "fixed"
            s["fixed_margin_per_lot"] = expiry_margin
            s["margin_percentage"] = 0.0
            s["leverage"] = 1.0
        else:
            # Legacy "percent" mode (or unknown) → preserve the original
            # behaviour: value is a % of notional with leverage 1.
            s["margin_percentage"] = expiry_margin
            s["leverage"] = 1.0
            s["fixed_margin_per_lot"] = 0.0

    # 8b) NRML (carry / overnight) orders lock the OVERNIGHT margin tier — but
    #     ONLY where NRML is the user's EXPLICIT carry choice (MCX / NSE). For
    #     CRYPTO and FOREX, NRML is the FORCED default (the panel has no MIS
    #     option — 24×7/24×5 markets), so a FRESH order there must use the
    #     INTRADAY tier (e.g. crypto 100× = 🪙97k/lot), NOT the overnight tier
    #     (33.33× = 🪙292k) — the latter only applies when the position actually
    #     ROLLS OVER at the market-control close (convert_intraday_to_carry
    #     re-margins it then). Applying overnight at order time demanded ~3× the
    #     margin and blocked the trade ("Need 292k, have 104k"). Skipped on expiry
    #     day (the expiry block above already set the tier).
    _pt_upper = str(getattr(product_type, "value", product_type) or "").upper()
    _seg_u = (segment_type or "").upper()
    _exch_u2 = str(getattr(instrument.exchange, "value", instrument.exchange) or "").upper()
    _forced_nrml_default = (
        "CRYPTO" in _seg_u
        or _exch_u2 in ("CRYPTO", "CDS")
        or "FOREX" in _seg_u
        or "FX" in _seg_u
    )
    if _pt_upper == "NRML" and not is_expiry_today and not _forced_nrml_default:
        _ol = s.get("overnight_leverage")
        _op = s.get("overnight_margin_percentage")
        _of = s.get("overnight_fixed_margin_per_lot")
        _osr = s.get("overnight_strike_margin_rate")
        if _ol:
            s["leverage"] = _ol
        if _op is not None:
            s["margin_percentage"] = _op
        if _of is not None:
            s["fixed_margin_per_lot"] = _of
        if _osr:
            s["strike_margin_rate"] = _osr

    # 9) margin check (all-Decimal arithmetic — never mix Decimal × float)
    margin_pct = to_decimal(s.get("margin_percentage") or 100.0) / to_decimal(100)
    leverage = to_decimal(s.get("leverage") or 1.0)
    if leverage <= 0:
        leverage = to_decimal(1)
    # Reference price for the notional / margin calc, in priority order:
    #   1. LIMIT / SL — user-entered price.
    #   2. `expected_price` from the order panel (the BUY/SELL price the
    #      user clicked). Same value the matching engine fills at, so the
    #      wallet locks exactly what the user will be charged.
    #   3. Live ask (BUY) or bid (SELL) — the actual fill side.
    #   4. LTP fallback for off-hours / missing depth.
    if price > 0:
        ref_price = price
    elif expected_price is not None and expected_price > 0:
        ref_price = expected_price
    else:
        try:
            quote = await market_data_service.get_quote(instrument.token)
            bid_raw = quote.get("bid")
            ask_raw = quote.get("ask")
            bid = to_decimal(bid_raw) if bid_raw not in (None, 0, "0") else None
            ask = to_decimal(ask_raw) if ask_raw not in (None, 0, "0") else None
        except Exception:
            bid = ask = None
        if action == OrderAction.BUY and ask is not None and ask > 0:
            ref_price = ask
        elif action == OrderAction.SELL and bid is not None and bid > 0:
            ref_price = bid
        else:
            ref_price = ltp

    # ── Circuit gate — like the real exchange (Zerodha/Upstox) ──────────
    # Two rules, only on NEW opening orders (closing/square-off must always be
    # allowed so you can exit); fail-open when no band data:
    #   1. CIRCUIT LOCK direction — when the stock is AT the upper circuit only
    #      SELL is possible (no sellers to buy from), and at the lower circuit
    #      only BUY (no buyers to sell to). So a BUY at the upper circuit / a
    #      SELL at the lower circuit is rejected.
    #   2. A LIMIT / SL priced OUTSIDE the band is rejected outright.
    if not is_reducing and not is_squareoff:
        lc, uc = await _circuit_limits(instrument)
        cur = ltp if (ltp and ltp > 0) else ref_price  # live market price
        if uc is not None and cur > 0 and cur >= uc and action == OrderAction.BUY:
            raise OrderRejectedError(
                f"{instrument.symbol} is at the UPPER CIRCUIT (🪙{uc}). "
                f"Only SELL is allowed — you can't BUY at the upper circuit.",
                code="UPPER_CIRCUIT_BUY",
            )
        if lc is not None and cur > 0 and cur <= lc and action == OrderAction.SELL:
            raise OrderRejectedError(
                f"{instrument.symbol} is at the LOWER CIRCUIT (🪙{lc}). "
                f"Only BUY is allowed — you can't SELL at the lower circuit.",
                code="LOWER_CIRCUIT_SELL",
            )
        if ref_price > 0:
            if uc is not None and ref_price > uc:
                raise OrderRejectedError(
                    f"Price 🪙{ref_price} is above the upper circuit 🪙{uc}.",
                    code="UPPER_CIRCUIT",
                )
            if lc is not None and ref_price < lc:
                raise OrderRejectedError(
                    f"Price 🪙{ref_price} is below the lower circuit 🪙{lc}.",
                    code="LOWER_CIRCUIT",
                )

    notional = to_decimal(quantity) * ref_price
    # Fixed-margin segments skip the notional × pct ÷ leverage formula
    # entirely — the admin's configured value is a flat 🪙/lot charged
    # once per lot. Anything else falls into the standard percent/times
    # path. (`margin_pct` is already 100% with the `leverage` set for
    # times mode, and is the literal percent for legacy percent mode.)
    fixed_per_lot = to_decimal(s.get("fixed_margin_per_lot") or 0)
    calc_mode = s.get("margin_calc_mode")
    strike_rate = to_decimal(s.get("strike_margin_rate") or 0)
    strike_pct_sell = (
        calc_mode == "strike_pct"
        and instrument.option_type is not None
        and action == OrderAction.SELL
        and not is_reducing
        and not is_squareoff
    )
    if strike_pct_sell:
        # Option-WRITING margin on the strike notional (the standard for
        # selling options): margin = strike × qty × rate. The rate is the
        # admin-typed decimal (0.03 intraday / 0.06 overnight), already picked
        # for this order's product_type by the resolver. This ignores the tiny
        # premium `ref_price` on purpose — a sold option's risk is the
        # underlying exposure, not the premium collected.
        #
        # Guard: if the strike or rate is missing we must NOT silently fall back
        # to the (much smaller) premium-based margin — that would let someone
        # write a deep-OTM option for almost nothing. Reject instead.
        # Strike may be NULL on some auto-mirrored option docs (256 seen live).
        # Fall back to parsing it from the (monthly) symbol so a valid sell isn't
        # wrongly rejected; the backfill fixes the stored data separately.
        strike_val = (
            to_decimal(str(instrument.strike))
            if instrument.strike is not None
            else (_strike_from_symbol(getattr(instrument, "symbol", None)) or Decimal("0"))
        )
        if strike_val <= 0 or strike_rate <= 0:
            raise OrderRejectedError(
                "Strike-based sell margin isn't configured for this contract "
                "(missing strike or rate) — contact your admin.",
                code="STRIKE_MARGIN_MISSING",
            )
        margin_required = strike_val * to_decimal(quantity) * strike_rate
    elif calc_mode == "fixed" and fixed_per_lot > 0:
        margin_required = to_decimal(lots) * fixed_per_lot
    else:
        margin_required = notional * margin_pct / leverage

    # USD-quoted instruments (Infoway: crypto / forex / metals / energy)
    # price `ref_price` in dollars — wallet runs in INR, so the margin we
    # lock must be in INR too. Multiply by the live USD/INR rate. Skip for
    # native-INR segments (NSE / BSE / MCX / NFO / BFO). Fixed-per-lot
    # values are admin-entered in INR already, so this conversion is
    # skipped for fixed mode.
    inst_segment = str(getattr(instrument.segment, "value", instrument.segment) or "")
    if (
        (market_data_service.is_usd_quoted_segment(segment_type) or market_data_service.is_usd_quoted_segment(inst_segment))
        and not (calc_mode == "fixed" and fixed_per_lot > 0)
        and not calc_mode == "strike_pct"
    ):
        usd_inr = to_decimal(market_data_service.get_usd_inr_rate())
        margin_required = margin_required * usd_inr
    wallet = await wallet_router.get(user.id, segment_type)  # type: ignore[arg-type]
    available = to_decimal(wallet.available_balance) + to_decimal(wallet.credit_limit)
    # FREE-MARGIN (dabba/CFD): a segment wallet's live floating P&L is buying
    # power too — a floating PROFIT lets the user open more, a floating LOSS
    # reduces it. Mirrors segment_wallet_service.block_margin so this pre-check
    # and the actual lock agree. (Main wallet already enforces free/equity.)
    try:
        from app.services import segment_wallet_service, wallet_kinds

        _kind = wallet_kinds.wallet_kind_for_segment(segment_type)
        if wallet_kinds.is_segment_kind(_kind):
            available += await segment_wallet_service.segment_float_pnl(user.id, _kind)
    except Exception:  # noqa: BLE001 — never let the free-margin add-on break validation
        pass
    # Closing/reducing orders don't lock new margin — they free it up — so
    # skip the funds + utilisation cap checks for them.
    if is_reducing or is_squareoff:
        margin_required = to_decimal(0)
    else:
        # ── Zero-capital opening guard (root-cause companion to the
        # risk_enforcer zero-capital stop-out) ──────────────────────────
        # A user whose available_balance + credit_limit is exhausted
        # (realised losses floored the wallet to 0, overflow parked in
        # settlement_outstanding) must NOT be able to open fresh exposure.
        # Without this, an opening order whose computed margin happened to
        # be 0 (fixed_per_lot = 0, margin_percentage = 0, or a stale
        # leverage config) sailed past the `margin_required > available`
        # check below — `0 > 0` is False — and created a position with
        # margin_used = 0. That is the exact state that left CL45900793
        # holding loss-making exposure with NO capital backing it and the
        # stop-out denominator (available + used_margin + credit_limit)
        # pinned at 0, which silently disabled stop-out for the account.
        if available <= to_decimal(0):
            raise InsufficientFundsError(
                "No funds available to open a new position. "
                "Close existing positions or add funds."
            )
        if margin_required > available:
            raise InsufficientFundsError(
                f"Need 🪙{margin_required:.2f}, have 🪙{available:.2f}"
            )

        # ── Portfolio leverage cap (aggregate, per-wallet) ──────────────
        # The funds check above only proves THIS leg's margin fits. It can't
        # see that the WHOLE wallet's blended leverage has drifted past the
        # intended max: a high-leverage leg (NIFTY 50×) locks little margin
        # for large notional, freeing room a low-leverage leg (BANKNIFTY
        # 33.33×) then fills, so Σ(notional) climbs above balance × cap even
        # though every leg passed its own margin. This gate bounds the wallet's
        # TOTAL exposure (existing open notional + this order) at
        # balance × cap, whatever each leg's own leverage is. Opening orders
        # only — the reducing/squareoff branch skips it, so exits always work.
        from app.core.config import settings as _cfg_cap
        from app.services import wallet_kinds as _wk_cap

        _cap_kind = _wk_cap.wallet_kind_for_segment(segment_type)
        _cap_lev = to_decimal(_cfg_cap.portfolio_leverage_caps.get(_cap_kind, 0) or 0)
        if _cap_lev > 0:
            # Wallet equity = total capital backing the book (free + locked +
            # credit). Matches the "balance" the user reads on the wallet card
            # (available_balance + used_margin), plus any credit line.
            _equity = (
                to_decimal(wallet.available_balance)
                + to_decimal(wallet.used_margin)
                + to_decimal(wallet.credit_limit)
            )
            _cap_amount = _equity * _cap_lev
            if _cap_amount > 0:
                _existing_notional = await _open_notional_for_kind(user.id, _cap_kind)
                _projected = _existing_notional + notional
                if _projected > _cap_amount:
                    _lbl = _wk_cap.LABELS.get(_cap_kind, _cap_kind)
                    raise OrderRejectedError(
                        f"Portfolio leverage limit: this order would take your "
                        f"{_lbl} exposure to 🪙{_projected:,.0f}, above the max "
                        f"🪙{_cap_amount:,.0f} ({_cap_lev:g}× of balance "
                        f"🪙{_equity:,.0f}). Reduce size or close a position first.",
                        code="PORTFOLIO_LEVERAGE_CAP",
                    )

    # 10) stop-loss mandatory
    if s.get("stop_loss_mandatory") and order_type not in (OrderType.SL, OrderType.SL_M):
        raise OrderRejectedError("Stop-loss is mandatory for this segment", code="SL_MANDATORY")

    # 11) market hours (skip for AMO and 24×7 segments)
    seg_upper = (segment_type or "").upper()
    exch_upper = str(getattr(instrument.exchange, "value", instrument.exchange) or "").upper()
    is_24x7 = "CRYPTO" in seg_upper or exch_upper == "CRYPTO"  # crypto runs 24×7
    # Forex + spot metals (XAU/XAG…) + energy (USOIL/UKOIL/NATGAS) all
    # follow the international 24×5 calendar — closed only on weekends.
    # They all sit on the virtual `CDS` exchange in our catalogue.
    is_24x5 = (
        "FOREX" in seg_upper
        or "FX" in seg_upper
        or "COMMODITIES" in seg_upper
        or "CDS" in seg_upper
        or exch_upper == "CDS"
    )
    is_mcx = "MCX" in seg_upper  # MCX has its own hours (~09:00-23:30 IST)

    # ── Super-admin MARKET CONTROL (per-segment trading hours) ──────────
    # When the SA has enabled a window for this segment, it OVERRIDES the default
    # calendar — so the SA can open/close ANY market at will, including the 24×7
    # CRYPTO and 24×5 FOREX. Blocks new OPENING orders outside the window; exits
    # (closing / square-off) stay allowed so a user can always flatten.
    if not is_squareoff and not is_reducing:
        from app.services.market_control_service import market_control_reason

        _mc_row = netting_service._seg_name_for(segment_type, getattr(instrument, "symbol", None))
        _mc_reason = await market_control_reason(_mc_row)
        if _mc_reason:
            raise MarketClosedError(_mc_reason)

    # ── Zerodha-connectivity gate (runs EVEN under ALLOW_TRADE_AT_LAST_PRICE) ─
    # ALLOW_TRADE_AT_LAST_PRICE lets users trade 24×7 at the last-known price
    # when the market is merely CLOSED — Zerodha stays logged in, it just stops
    # ticking. But when Zerodha is genuinely DISCONNECTED / logged out / the
    # token expired, that "last price" is a frozen, untrustworthy value and a
    # new OPEN must NOT fill against it (operator: "after zerodha disconnected,
    # still able to trade in MCX"). The whole market-hours + feed-freeze block
    # below is skipped when `_allow_last_price` is on, so that guard never ran —
    # hence this dedicated gate OUTSIDE it. Connection STATE (not tick-age) is
    # what separates the two cases: closed-but-connected → allow; disconnected
    # → block. Exits (squareoff / reduce-only) and AMO stay allowed so a user
    # can always flatten or queue an order for the next session.
    if not is_squareoff and not is_reducing and not is_amo:
        _z_fed = not (
            market_data_service.is_usd_quoted_segment(segment_type)
            or market_data_service.is_usd_quoted_segment(getattr(instrument, "segment", None))
        )
        if _z_fed:
            from app.services.zerodha_service import zerodha as _zerodha_conn

            _feed_ok = True
            try:
                _feed_ok = await _zerodha_conn.is_feed_connected()
            except Exception:  # noqa: BLE001 — probe error must not halt trading
                _feed_ok = True
            if not _feed_ok:
                raise MarketClosedError(
                    f"{instrument.symbol}: the Zerodha price feed is disconnected "
                    f"— new orders are blocked so nothing fills at a stale price. "
                    f"You can still close existing positions; try again once the "
                    f"feed reconnects."
                )

    # Squareoff orders (admin force-close, user kill-switch, risk
    # auto-flatten, SL/TP/stop-out fires) intentionally bypass the
    # market-hours guard. We're a B-book — matching is internal, prices
    # come from the cached LTP — so closing a position never needs the
    # external exchange to be live. Before this exemption the admin's
    # "Close" button on the Position Management page silently 400'd with
    # `MarketClosedError` after-hours, leaving the admin with no way to
    # flatten a runaway position outside trading hours.
    # When ALLOW_TRADE_AT_LAST_PRICE is on, opening orders skip the market-hours
    # + live-tick gates entirely and fill at the last-known price (demo/challenge
    # platform — tradeable 24×7). The matching engine's zero-price guard is the
    # backstop against a genuinely dead 0-price.
    from app.core.config import settings as _cfg
    _allow_last_price = bool(getattr(_cfg, "ALLOW_TRADE_AT_LAST_PRICE", False))
    if not is_amo and not is_24x7 and not is_squareoff and not _allow_last_price:
        ist = now_ist()

        # 24×5 (forex / metals / energy): closed only on weekends (Sat full-day;
        # Sun close before 17:30 ET ≈ 03:00 IST Mon)
        if is_24x5:
            wd = ist.weekday()  # Mon=0 ... Sun=6
            if wd == 5 or (wd == 6 and ist.hour < 4):
                raise MarketClosedError("Forex market is closed for the weekend.")
        else:
            if is_weekend(ist.date()):
                raise MarketClosedError("Market is closed (weekend). Place AMO instead.")
            # holiday lookup (only Indian exchanges)
            h = await TradingHoliday.find_one(
                TradingHoliday.holiday_date == ist.date(),
                TradingHoliday.exchange == instrument.exchange,
            )
            if h is not None:
                if h.is_full_day:
                    raise MarketClosedError(f"Holiday: {h.description}. Place AMO instead.")
                # Partial-day holiday with a special session window — e.g. MCX
                # runs an EVENING-only session (17:00–23:30) on a day NSE/BSE
                # are fully closed. We honour the admin-set open_time/close_time
                # (stored as "HH:MM" strings on TradingHoliday) so trades are
                # blocked OUTSIDE that window — and the snapshot-fed feed gate
                # can't leak a pre-session order. A row with is_full_day=false +
                # open_time="17:00" → blocked till 17:00, open after, no manual
                # toggle. Malformed time strings fail-open (defensive parse).
                _ot = _ct = None
                try:
                    if h.open_time:
                        _ot = parse_hhmm(h.open_time)
                    if h.close_time:
                        _ct = parse_hhmm(h.close_time)
                except Exception:
                    _ot = _ct = None
                if _ot is not None and ist.time() < _ot:
                    raise MarketClosedError(
                        f"{h.description}: session opens at {h.open_time} IST. Place AMO instead."
                    )
                if _ct is not None and ist.time() > _ct:
                    raise MarketClosedError(
                        f"{h.description}: session closed at {h.close_time} IST."
                    )

            from app.core.config import settings as cfg

            if is_mcx:
                # MCX: 09:00 – 23:30 IST (winter) / 23:55 IST (summer evening session)
                # We use a generous 09:00 – 23:30 window.
                from datetime import time as _t

                if not (_t(9, 0) <= ist.time() <= _t(23, 30)):
                    raise MarketClosedError("MCX is closed. Place AMO instead.")
            else:
                # NSE / BSE equities + F&O: 09:15 – 15:30 IST
                open_t = parse_hhmm(cfg.MARKET_OPEN_TIME)
                close_t = parse_hhmm(cfg.MARKET_CLOSE_TIME)
                if not (open_t <= ist.time() <= close_t):
                    raise MarketClosedError("Market is closed. Place AMO instead.")

        # ── 11b) Live-tick sanity (catches late opens / mid-session halts)
        #
        # The static clock-based checks above can't catch the case where
        # the exchange schedule SAYS the market is open but the session
        # hasn't actually started (or has stopped mid-day for a halt).
        # 28-May 2026: MCX was scheduled 09:00 IST but the exchange
        # didn't release the feed until 17:00; orders went through at
        # zero/stale prices for 8 hours, costing the admin real money.
        #
        # This guard belts-and-braces the wall-clock check by requiring
        # at least one fresh tick from Zerodha for THIS specific
        # instrument within the last `_TICK_MAX_AGE_SEC` seconds. During
        # an active session Kite streams continuously, so a 60-second
        # gap is a strong "session not live" signal. The threshold is
        # generous enough to tolerate brief WS hiccups without false-
        # rejecting legitimate orders.
        #
        # This probe reads ZERODHA's last-tick age, so it ONLY applies to
        # Zerodha-fed segments (NSE / BSE / NFO / BFO / MCX). Infoway-fed
        # segments are exempt — Zerodha never ticks them, so the probe is
        # always None and would false-reject every order even with a live
        # price on the chart:
        #   • crypto (24×7) — already excluded by the outer guard.
        #   • forex / spot metals (XAUUSD…) / energy (24×5 → is_24x5).
        # 05-Jun-2026: XAUUSD BUY was blocked with "No live prices" despite
        # a live Infoway chart + bid/ask — this `not is_24x5` guard fixes it.
        # The wall-clock weekend check (11a) still gates these 24×5 markets.
        if not is_24x5:
            import time as _vt

            from app.services.market_data_service import _read_mdlive
            from app.services.zerodha_service import zerodha as _zerodha_for_tick_check

            # ── PRIMARY gate: the EXCHANGE's own packet age (snapshot-proof) ──
            # The wall-clock window above says MCX is "open" from 09:00, but on
            # a day MCX only runs the evening session (e.g. an NSE holiday) the
            # exchange sends nothing until 17:00 — EXCEPT a stale snapshot Kite
            # resends on every (re)subscribe, which keeps `received_at` fresh and
            # let orders through at last-session prices (28-May incident). The
            # exchange's OWN `exchange_timestamp` is not fooled: on a closed
            # session it's the PREVIOUS session's time (hours old). So if a fresh
            # exchange timestamp exists, the session is genuinely live; if it's
            # hours stale, the session is closed regardless of the clock. This
            # auto-handles every holiday / late-open / evening-only session with
            # zero calendar maintenance.
            #
            # 600 s tolerance: a live session streams exchange packets well
            # within this even for quiet/illiquid contracts, while a pre-open /
            # closed session is hours stale — so this never false-rejects a live
            # contract yet always catches the closed-session case.
            _SESSION_STALE_SEC = 600

            # FEED-FREEZE threshold (operator spec, 29-Aug): during a live
            # session a Zerodha-fed instrument's exchange packets stream
            # sub-second, so if the freshest packet is older than this the
            # price is FROZEN — the WS stalled, the account isn't logged in,
            # or the instrument is mid-halt. Booking an OPEN against a stuck
            # price fills at a level nobody is trading at. Tunable; the
            # operator asked for ~2s (they trade liquid index futures that
            # tick many times a second). Raise it if quiet/illiquid contracts
            # start false-rejecting on their natural inter-trade gaps.
            _FEED_FREEZE_MAX_AGE_SEC = 2.0

            _ex_age: float | None = None
            try:
                _ex_age = _zerodha_for_tick_check.get_exchange_ts_age_sec(instrument.token)
            except Exception:
                _ex_age = None
            # Multi-worker: ticks_by_token is warm only on the feed-leader, but
            # the leader mirrors `exchange_timestamp` into mdlive:{token}, so a
            # non-leader reads the live-session signal from there.
            if _ex_age is None:
                try:
                    _snap = await _read_mdlive(instrument.token)
                    _ets = float((_snap or {}).get("exchange_timestamp") or 0)
                    if _ets > 0:
                        _ex_age = _vt.time() - _ets
                except Exception:
                    _ex_age = None

            if _ex_age is not None:
                # Authoritative exchange-time signal present → it decides.
                if _ex_age > _SESSION_STALE_SEC:
                    raise MarketClosedError(
                        f"{instrument.symbol}: no live session — the exchange feed "
                        f"is {int(_ex_age)}s stale, so the market appears closed "
                        f"(pre-open / holiday session). Try once prices resume, or "
                        f"place an AMO order."
                    )
                # FEED FROZEN mid-session: the session is recent (< stale
                # window) but the freshest packet is older than the freeze
                # threshold → the price is stuck (Zerodha WS stalled / not
                # logged in / mid-halt). Block OPENS so nothing fills at a
                # stale price. EXITS are exempt (`is_squareoff`) so a user can
                # always flatten, and the auto SL/TP poller + risk stop-out
                # bypass this validator, so protective closes are never gated.
                if not is_squareoff and _ex_age > _FEED_FREEZE_MAX_AGE_SEC:
                    raise MarketClosedError(
                        f"{instrument.symbol}: live prices are stuck — no fresh "
                        f"tick for {int(_ex_age)}s (the Zerodha feed may be "
                        f"disconnected or frozen). Order blocked to prevent a "
                        f"stale-price fill. Try again once prices resume."
                    )
                # Fresh exchange timestamp → genuinely live → allow.
            else:
                # ── No exchange timestamp anywhere. For an INR-native
                # (Zerodha-fed) instrument that is not a quirk, it is the
                # symptom: no tick in `ticks_by_token` AND nothing mirrored
                # into `mdlive` means the WS is down or this token was never
                # subscribed. Booking an open here fills at whatever price was
                # last seen, which is exactly what the operator hit after
                # disconnecting Zerodha.
                #
                # Asking `mdlive is not None` cannot catch it: the tick loop
                # rewrites every subscribed token's key once a second from the
                # last known quote, with a 30 s TTL, so a frozen price keeps
                # its key alive indefinitely. Presence was never freshness.
                #
                # USD-quoted segments (Infoway crypto / forex) carry no
                # exchange timestamp by design, so they keep the old
                # received-at heuristic until that feed grows a freshness
                # stamp of its own.
                _inst_seg_now = getattr(instrument, "segment", None)
                _zerodha_fed = not (
                    market_data_service.is_usd_quoted_segment(segment_type)
                    or market_data_service.is_usd_quoted_segment(_inst_seg_now)
                )
                if _zerodha_fed and not is_squareoff:
                    raise MarketClosedError(
                        f"{instrument.symbol}: no live price feed right now — "
                        f"nothing has arrived from the exchange for this "
                        f"contract. Order blocked so it can't fill at a stale "
                        f"price. Please try after some time."
                    )

                _TICK_MAX_AGE_SEC = 60
                try:
                    _tick_age = _zerodha_for_tick_check.get_last_tick_age_sec(instrument.token)
                except Exception:
                    _tick_age = 0.0
                if _tick_age is None or _tick_age > _TICK_MAX_AGE_SEC:
                    _feed_live = False
                    try:
                        _live_snap = await _read_mdlive(instrument.token)
                        _feed_live = _live_snap is not None
                    except Exception:
                        _feed_live = False
                    if not _feed_live:
                        raise MarketClosedError(
                            f"No live prices for {instrument.symbol} in the last "
                            f"{_TICK_MAX_AGE_SEC}s — exchange session appears closed "
                            f"or feed is down. Try again once prices resume, or "
                            f"place an AMO order."
                        )

    # Build snapshot for the order document
    settings_snapshot = {
        "segment_type": segment_type,
        "margin_percentage": s.get("margin_percentage"),
        "leverage": s.get("leverage"),
        "commission_type": str(s.get("commission_type")) if s.get("commission_type") else None,
        "commission_value": s.get("commission_value"),
        "min_brokerage": s.get("min_brokerage"),
        "stop_loss_mandatory": s.get("stop_loss_mandatory"),
        "auto_squareoff_time": s.get("auto_squareoff_time"),
        "m2m_squareoff_percent": s.get("m2m_squareoff_percent"),
    }

    return ValidatedOrder(settings=settings_snapshot, netting_settings=resolved, margin_required=margin_required, ltp=ltp)
