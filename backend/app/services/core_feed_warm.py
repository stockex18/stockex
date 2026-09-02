"""Keep the three main index option chains permanently on the feed.

NIFTY, BANKNIFTY and SENSEX are what almost every user opens, and each one
used to be subscribed the moment somebody looked at it — a fresh subscription
per strike, per viewer, competing for the same 1,500-slot list that the LRU
then evicted from. The second viewer paid the same cost as the first, and the
chain rendered blank for a second or two while Kite caught up.

They do not have to be on demand. There are only ever a few dozen strikes near
the money, they are wanted every single session, and nothing about them is
per-user. Warming them once and holding them means every chain read is served
out of what the feed already stored.

Leader-only, and deliberately narrow:

  * the three underlyings the option-chain picker offers, and nothing else
  * the nearest expiry, where essentially all the volume is
  * ATM +/- N strikes, both sides, N from the same `strikes_around_atm`
    setting the chain itself renders with — so the warm set and what the user
    sees can never disagree

ATM moves during the day, so this re-runs on a timer rather than at boot.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The picker's underlyings. Kept in sync with `_DEFAULT_UNDERLYINGS` in
#: `api/v1/user/option_chain.py` and the UNDERLYINGS list in the mobile chain.
CORE_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "SENSEX")

#: Strikes each side of the money. Six is what the operator asked for and is
#: roughly what fits on a phone screen without scrolling.
DEFAULT_WARM_STRIKES = 6

#: Hard ceiling on one warm pass. 3 underlyings x (2N+1) strikes x 2 sides is
#: about 78 at N=6; anything far above that means a bad ladder read, and
#: silently subscribing hundreds of strikes is how the list filled up before.
_MAX_WARM_TOKENS = 200


async def _spot_for(root: str) -> float:
    """Live spot for an index underlying, or 0 when it cannot be read."""
    from app.api.v1.user.option_chain import _underlying_spot

    try:
        return float(await _underlying_spot(root) or 0)
    except Exception:  # noqa: BLE001
        return 0.0


async def collect_core_tokens(strikes: int = DEFAULT_WARM_STRIKES) -> dict[int, dict[str, str]]:
    """{token: {symbol, exchange}} for the three chains' near-the-money legs.

    Never raises: a cold catalog or an unreadable spot yields fewer tokens (or
    none), which just means those strikes stay on the old on-demand path.
    """
    from datetime import datetime, timezone

    from app.models.instrument import Instrument

    out: dict[int, dict[str, str]] = {}
    now = datetime.now(timezone.utc)

    for root in CORE_UNDERLYINGS:
        try:
            spot = await _spot_for(root)
            if spot <= 0:
                logger.debug("core_warm_no_spot", extra={"root": root})
                continue

            # Nearest expiry that has not passed. One query, indexed on expiry.
            nearest = await Instrument.find(
                {
                    "symbol": {"$regex": f"^{root}\\d"},
                    "instrument_type": {"$in": ["CE", "PE"]},
                    "expiry": {"$gte": now},
                    "is_active": True,
                }
            ).sort("+expiry").limit(1).to_list()
            if not nearest:
                continue
            expiry = nearest[0].expiry

            rows = await Instrument.find(
                {
                    "symbol": {"$regex": f"^{root}\\d"},
                    "instrument_type": {"$in": ["CE", "PE"]},
                    "expiry": expiry,
                    "is_active": True,
                }
            ).to_list()

            # Rank by distance from the money and keep the closest 2N+1
            # STRIKES — not rows, or a CE-heavy ladder would crowd out the
            # puts at the same price.
            by_strike: dict[float, list[Any]] = {}
            for r in rows:
                try:
                    k = float(str(r.strike))
                except (TypeError, ValueError):
                    continue
                if k > 0:
                    by_strike.setdefault(k, []).append(r)
            near = sorted(by_strike, key=lambda k: abs(k - spot))[: strikes * 2 + 1]

            for k in near:
                for r in by_strike[k]:
                    try:
                        tok = int(r.token)
                    except (TypeError, ValueError):
                        continue
                    ex = getattr(r, "exchange", None)
                    out[tok] = {
                        "symbol": r.symbol,
                        "exchange": (ex.value if hasattr(ex, "value") else str(ex or "NSE")),
                    }
        except Exception:  # noqa: BLE001 — one bad chain must not stop the rest
            logger.debug("core_warm_root_failed", extra={"root": root}, exc_info=True)

    if len(out) > _MAX_WARM_TOKENS:
        logger.warning(
            "core_warm_token_count_unexpected",
            extra={"count": len(out), "cap": _MAX_WARM_TOKENS},
        )
        return {}
    return out


async def warm_core_feed_once(strikes: int = DEFAULT_WARM_STRIKES) -> int:
    """Subscribe the core chains and put them in `_subscribed` so `tick_loop`
    mirrors them. Idempotent — a steady state re-subscribes nothing."""
    from app.services import market_data_service as mds
    from app.services.zerodha_service import zerodha

    tokens = await collect_core_tokens(strikes)
    if not tokens:
        return 0
    try:
        await zerodha.subscribe_tokens_on_demand(list(tokens), tokens)
    except Exception:  # noqa: BLE001
        logger.warning("core_warm_subscribe_failed", exc_info=True)
        return 0
    # `_subscribed` is the gate tick_loop reads to mirror a quote into
    # `mdlive` — subscribing on Kite alone leaves the chain invisible to every
    # non-leader worker.
    mds.subscribe([str(t) for t in tokens])
    return len(tokens)


async def core_feed_warm_loop(interval_sec: float = 300.0) -> None:
    """Leader-only. Re-runs because the money moves: a chain warmed at 09:15
    around 24,000 is the wrong ladder by afternoon if the index has travelled.
    First pass runs immediately."""
    logger.info("core_feed_warm_loop_started interval_sec=%s", interval_sec)
    try:
        while True:
            try:
                n = await warm_core_feed_once()
                if n:
                    logger.info("core_feed_warmed", extra={"tokens": n})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("core_feed_warm_iter_failed", exc_info=True)
            await asyncio.sleep(interval_sec)
    finally:
        logger.info("core_feed_warm_loop_stopped")
