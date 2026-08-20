"""Public (unauthenticated) market snapshot for the marketing site.

Every market route under ``/api/v1/user`` requires a signed-in user, so
the landing page had no way to show real prices and shipped a hardcoded
sample array instead (see the note that used to sit in
``components/landing/live-ticker.jsx``). This is that missing endpoint.

Scope is deliberately narrow — it is NOT a general quotes API:

* the instrument list is a fixed, server-side curation. A visitor cannot
  ask for arbitrary tokens, so this can never be used to scrape the feed;
* it returns display fields only (ltp / change / change_pct). No bid/ask,
  no depth, no OHLC — nothing an unauthenticated client could trade on;
* responses are cached process-wide for a few seconds, so public traffic
  costs the upstream feed nothing regardless of request volume.

The companion realtime path is the ``/ws/marketdata`` socket, which is
already public (its ``token`` query param is optional). The landing page
takes its first paint from this endpoint — which also tells it which
tokens exist — then subscribes to that socket for live ticks.

Mounted at ``/api/v1/market`` from ``app/main.py``, alongside
``/api/v1/branding`` — platform-level lookups, not user-scoped.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any

from fastapi import APIRouter

from app.models._base import InstrumentType
from app.models.instrument import Instrument
from app.schemas.common import APIResponse
from app.services import market_data_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market-public"])


# ── Curation ─────────────────────────────────────────────────────────
#
# `symbols` is an ORDERED candidate list, not an alias set: the first one
# that resolves wins. Index naming differs between the Zerodha dump and
# our own seed ("NIFTY 50" vs "NIFTY"), and MCX contracts are futures
# whose symbol carries the expiry, so a single literal would resolve on
# one deployment and 404 on the next.
#
# `category` drives the filter tabs on the landing table (All / Stocks /
# Indices / Commodities / Currency) — keep the values in sync with
# `components/landing/pricing-table-section.jsx`.
_WATCHLIST: list[dict[str, Any]] = [
    {"key": "RELIANCE",   "label": "RELIANCE",   "category": "Stocks",      "exchange": "NSE", "kind": "cash",   "symbols": ["RELIANCE"]},
    {"key": "TCS",        "label": "TCS",        "category": "Stocks",      "exchange": "NSE", "kind": "cash",   "symbols": ["TCS"]},
    {"key": "HDFCBANK",   "label": "HDFCBANK",   "category": "Stocks",      "exchange": "NSE", "kind": "cash",   "symbols": ["HDFCBANK"]},
    {"key": "INFY",       "label": "INFY",       "category": "Stocks",      "exchange": "NSE", "kind": "cash",   "symbols": ["INFY"]},
    {"key": "ICICIBANK",  "label": "ICICIBANK",  "category": "Stocks",      "exchange": "NSE", "kind": "cash",   "symbols": ["ICICIBANK"]},
    {"key": "TATAMOTORS", "label": "TATAMOTORS", "category": "Stocks",      "exchange": "NSE", "kind": "cash",   "symbols": ["TATAMOTORS"]},
    {"key": "NIFTY50",    "label": "NIFTY 50",   "category": "Indices",     "exchange": "NSE", "kind": "cash",   "symbols": ["NIFTY 50", "NIFTY50", "NIFTY"]},
    {"key": "BANKNIFTY",  "label": "BANK NIFTY", "category": "Indices",     "exchange": "NSE", "kind": "cash",   "symbols": ["NIFTY BANK", "BANKNIFTY"]},
    {"key": "SENSEX",     "label": "SENSEX",     "category": "Indices",     "exchange": "BSE", "kind": "cash",   "symbols": ["SENSEX"]},
    {"key": "GOLD",       "label": "GOLD",       "category": "Commodities", "exchange": "MCX", "kind": "future", "symbols": ["GOLD"]},
    {"key": "CRUDEOIL",   "label": "CRUDE",      "category": "Commodities", "exchange": "MCX", "kind": "future", "symbols": ["CRUDEOIL"]},
    {"key": "USDINR",     "label": "USDINR",     "category": "Currency",    "exchange": "CDS", "kind": "future", "symbols": ["USDINR"]},
]

# Resolved symbol → token. Instruments churn only on the expiry-rollover
# boundary, so this is cached far longer than the quotes themselves.
_TOKEN_TTL_SEC = 600
_token_cache: dict[str, Any] = {"at": 0.0, "rows": []}

# Whole-response cache. The upstream tick loop runs at 250 ms; 3 s here
# means a public flood costs at most ~0.3 upstream reads/second while
# still looking live next to the WS stream that follows it.
_SNAPSHOT_TTL_SEC = 3.0
_snapshot_cache: dict[str, Any] = {"at": 0.0, "payload": []}


async def _resolve_one(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Find the tradable Instrument for one watchlist entry.

    Two resolution modes, because the two families are stored differently:

    * ``kind: "cash"`` — equities and indices carry the plain root as
      ``symbol`` ("RELIANCE", "NIFTY 50"), so an anchored exact match is
      both correct and unambiguous.
    * ``kind: "future"`` — MCX and CDS contracts store the FULL contract
      symbol ("GOLD25FEBFUT"), never the bare root, so an exact match on
      "GOLD" finds nothing. Matching is anchored on root + Zerodha's
      ``YYMMM`` + ``FUT`` instead. The digit after the root is what keeps
      "GOLD" from also matching GOLDM (Gold Mini) or GOLDGUINEA, which a
      plain prefix would swallow — and those are different contracts at
      very different price points.

    Futures then resolve to the NEAREST UNEXPIRED contract: the root
    alone is ambiguous across months, and the front month is what a price
    ticker means by "GOLD".
    """
    is_future = entry.get("kind") == "future"
    for sym in entry["symbols"]:
        if is_future:
            # `FUT` optional: NFO/MCX write "GOLD25FEBFUT" but the CDS
            # dump is not consistent about the suffix. The instrument_type
            # filter below is what actually guarantees a future, so the
            # suffix only has to not EXCLUDE a valid contract.
            pattern = f"^{sym}[0-9]{{2}}[A-Z]{{3}}(FUT)?$"
            q: dict[str, Any] = {
                "symbol": {"$regex": pattern, "$options": "i"},
                "instrument_type": InstrumentType.FUT.value,
                "is_active": True,
            }
        else:
            q = {
                "symbol": {"$regex": f"^{sym}$", "$options": "i"},
                "is_active": True,
            }
        try:
            rows = await Instrument.find(q).to_list()
        except Exception:
            logger.debug("market_public_lookup_failed sym=%s", sym, exc_info=True)
            continue
        if not rows:
            continue

        # Prefer the expected exchange when the symbol exists on several.
        want = str(entry.get("exchange") or "").upper()
        exact = [r for r in rows if str(getattr(r, "exchange", "")).upper() == want]
        pool = exact or rows

        dated = [r for r in pool if getattr(r, "expiry", None)]
        if dated:
            today = date.today()
            live = sorted(
                (r for r in dated if r.expiry and r.expiry >= today),
                key=lambda r: r.expiry,
            )
            pick = live[0] if live else None
        else:
            pick = pool[0]

        if pick is None:
            continue
        return {
            "key": entry["key"],
            "label": entry["label"],
            "category": entry["category"],
            "exchange": str(getattr(pick, "exchange", "") or entry.get("exchange") or ""),
            "token": str(pick.token),
            "name": pick.name,
        }
    return None


async def _resolved_watchlist() -> list[dict[str, Any]]:
    now = time.time()
    if _token_cache["rows"] and (now - _token_cache["at"]) < _TOKEN_TTL_SEC:
        return _token_cache["rows"]
    found = await asyncio.gather(
        *(_resolve_one(e) for e in _WATCHLIST), return_exceptions=True
    )
    rows = [r for r in found if isinstance(r, dict)]
    # Only refresh the cache stamp on a NON-EMPTY resolve. An empty result
    # means the instrument collection isn't seeded yet (fresh deploy, or
    # the Zerodha boot hasn't finished) — caching that for 10 minutes
    # would leave the landing page blank long after the data arrived.
    if rows:
        _token_cache["rows"] = rows
        _token_cache["at"] = now
    return rows


@router.get("/snapshot", response_model=APIResponse[list])
async def snapshot() -> APIResponse[list]:
    """Curated market snapshot for the public marketing pages.

    Returns one row per resolvable instrument. Rows whose feed has no
    positive LTP are omitted rather than sent as ``0`` — a marketing page
    showing a zero price reads as broken, and an absent row simply
    shortens the ticker.
    """
    now = time.time()
    if _snapshot_cache["payload"] and (now - _snapshot_cache["at"]) < _SNAPSHOT_TTL_SEC:
        return APIResponse(data=_snapshot_cache["payload"])

    rows = await _resolved_watchlist()
    if not rows:
        return APIResponse(data=[], message="market_data_unavailable")

    quotes = await asyncio.gather(
        *(market_data_service.get_quote(r["token"]) for r in rows),
        return_exceptions=True,
    )

    out: list[dict[str, Any]] = []
    for row, q in zip(rows, quotes):
        if not isinstance(q, dict):
            continue
        try:
            ltp = float(q.get("ltp") or 0)
        except (TypeError, ValueError):
            continue
        if ltp <= 0:
            continue
        try:
            change = float(q.get("change") or 0)
            change_pct = float(q.get("change_pct") or 0)
        except (TypeError, ValueError):
            change, change_pct = 0.0, 0.0
        out.append({
            **row,
            "ltp": round(ltp, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
        })

    if out:
        _snapshot_cache["payload"] = out
        _snapshot_cache["at"] = now
    return APIResponse(data=out)
