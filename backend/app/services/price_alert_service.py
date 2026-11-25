"""Price alerts: fire a user's alert when the live price reaches its target.

Client request (25 Nov 2026): "notification on the mobile app once the price
is reached". Until now an alert was only SAVED — nothing ever compared it with
the market, so no alert had ever triggered.

Every `SCAN_INTERVAL_SEC`, on the FEED LEADER (it reads the leader's in-process
prices, like the pending-order poller — on any other worker they are cold):

  1. Take every active, untriggered LTP_ABOVE / LTP_BELOW alert.
  2. Skip the ones whose market is shut right now — the same gate the
     pending-order poller uses. Out of session the cached LTP is the last
     tick of the previous session; firing on it would tell the user a price
     was reached that nobody traded at.
  3. Read the live LTP (`get_ltp_live`, the poller's price). LTP_ABOVE fires
     at LTP >= target, LTP_BELOW at LTP <= target. An alert set on the wrong
     side of the market therefore fires on the next scan — the condition is
     already true.
  4. Claim the alert with ONE conditional update (still active and not
     triggered → triggered, inactive). Only the scan that wins the claim
     notifies, so a leader hand-over can never send the same alert twice.
  5. Notify: a bell Notification row, a live `user:{id}:alerts` event (toast
     + sound in an open app), and a Web Push (phone tray, works with the app
     closed or the phone locked — once VAPID keys are configured).

Alerts fire ONCE: a triggered alert stays in the list as "Triggered" and does
not re-arm. PERCENT_CHANGE / VOLUME_SPIKE are not offered by the app and are
not checked.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from bson import Decimal128

from app.models.alert import AlertType, PriceAlert
from app.utils.decimal_utils import to_decimal
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

#: How often active alerts are compared with the live price. The scan is one
#: indexed query plus an in-memory price read per instrument.
SCAN_INTERVAL_SEC = 1.0

_CHECKED = (AlertType.LTP_ABOVE.value, AlertType.LTP_BELOW.value)

_running = False


def _target(a: PriceAlert) -> Decimal | None:
    if a.target_price is None:
        return None
    try:
        d = to_decimal(a.target_price)
    except Exception:  # noqa: BLE001 — a malformed target is never reached
        return None
    return d if d > 0 else None


def reached(alert_type: str, ltp: Decimal, target: Decimal) -> bool:
    """Has `ltp` reached `target` for this alert type?"""
    if alert_type == AlertType.LTP_ABOVE.value:
        return ltp >= target
    if alert_type == AlertType.LTP_BELOW.value:
        return ltp <= target
    return False


def _fmt(v: Decimal) -> str:
    """₹ amount with Indian grouping, trailing zeros trimmed (1,20,750 / 101.5)."""
    q = v.quantize(Decimal("0.01"))
    whole, _, frac = f"{q:.2f}".partition(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    frac = frac.rstrip("0")
    return ("-" if neg else "") + whole + (f".{frac}" if frac else "")


def alert_message(a: PriceAlert, target: Decimal, ltp: Decimal) -> tuple[str, str]:
    """(title, body) for the notification."""
    sym = a.instrument.symbol or a.instrument.trading_symbol or "Price alert"
    word = "rose above" if a.alert_type == AlertType.LTP_ABOVE else "fell below"
    title = f"🔔 {sym} price alert"
    body = f"{sym} {word} ₹{_fmt(target)} — LTP ₹{_fmt(ltp)}"
    if a.note:
        body += f"\nNote: {a.note}"
    return title, body


async def _claim(a: PriceAlert, ltp: Decimal) -> bool:
    """Mark the alert triggered, only if nobody else has. True when we won."""
    res = await PriceAlert.get_motor_collection().update_one(
        {"_id": a.id, "is_active": True, "is_triggered": False},
        {
            "$set": {
                "is_triggered": True,
                "is_active": False,
                "triggered_at": now_utc(),
                "triggered_price": Decimal128(str(ltp)),
                "updated_at": now_utc(),
            },
            "$inc": {"triggered_count": 1},
        },
    )
    return res.modified_count == 1


async def _notify(a: PriceAlert, target: Decimal, ltp: Decimal) -> None:
    """Bell row + live event + Web Push. Each part best-effort: one failing
    must not stop the others, nor the scan."""
    from app.models.notification import Notification, NotificationLevel, NotificationType

    title, body = alert_message(a, target, ltp)
    data: dict[str, Any] = {
        "kind": "price_alert",
        "alert_id": str(a.id),
        "symbol": a.instrument.symbol,
        "token": a.instrument.token,
        "alert_type": a.alert_type.value,
        "target_price": str(target),
        "ltp": str(ltp),
    }
    try:
        await Notification(
            user_id=a.user_id,
            type=NotificationType.PRICE_ALERT,
            level=NotificationLevel.INFO,
            title=title,
            message=body,
            data=data,
        ).insert()
    except Exception:  # noqa: BLE001
        logger.warning("price_alert_notification_failed", extra={"alert_id": str(a.id)})
    try:
        from app.core.redis_client import publish

        await publish(
            f"user:{a.user_id}:alerts",
            {"type": "price_alert", "title": title, "message": body, **data},
        )
    except Exception:  # noqa: BLE001
        logger.warning("price_alert_publish_failed", extra={"alert_id": str(a.id)})
    try:
        from app.services import push_service

        # One tray row per alert; tapping it opens the Alerts page.
        await push_service.send_to_user(
            a.user_id, title=title, body=body, url="/alerts", tag=f"price-alert-{a.id}"
        )
    except Exception:  # noqa: BLE001
        logger.warning("price_alert_push_failed", extra={"alert_id": str(a.id)})


async def scan_once() -> int:
    """One pass. Returns how many alerts fired. Never raises for one bad alert."""
    from app.services import market_data_service
    from app.services.matching_engine import resting_order_closed_gate

    rows = await PriceAlert.find(
        {"is_active": True, "is_triggered": False, "alert_type": {"$in": list(_CHECKED)}}
    ).to_list()
    if not rows:
        return 0

    closed = await resting_order_closed_gate(rows)
    ltp_cache: dict[str, Decimal | None] = {}
    fired = 0
    for a in rows:
        try:
            if closed(a):
                continue
            target = _target(a)
            if target is None:
                continue
            tok = str(a.instrument.token)
            if tok not in ltp_cache:
                v = market_data_service.get_ltp_live(tok)
                ltp_cache[tok] = v if v is not None and v > 0 else None
            ltp = ltp_cache[tok]
            if ltp is None or not reached(a.alert_type.value, ltp, target):
                continue
            if not await _claim(a, ltp):
                continue
            fired += 1
            logger.info(
                "price_alert_triggered",
                extra={
                    "alert_id": str(a.id),
                    "user_id": str(a.user_id),
                    "symbol": a.instrument.symbol,
                    "target": str(target),
                    "ltp": str(ltp),
                },
            )
            await _notify(a, target, ltp)
        except Exception:  # noqa: BLE001
            logger.exception("price_alert_check_failed", extra={"alert_id": str(a.id)})
    return fired


async def price_alert_loop(interval_sec: float = SCAN_INTERVAL_SEC) -> None:
    """Background loop launched from the lifespan, on the feed leader."""
    global _running
    if _running:
        return
    _running = True
    logger.info("price_alert_loop_started", extra={"interval_sec": interval_sec})
    try:
        while _running:
            try:
                await scan_once()
            except Exception:  # noqa: BLE001
                logger.exception("price_alert_scan_failed")
            await asyncio.sleep(interval_sec)
    finally:
        _running = False
        logger.info("price_alert_loop_stopped")


def stop_price_alert_loop() -> None:
    global _running
    _running = False
