"""Our Zerodha instrument → its Fyers symbol, rebuilt once a day.

Fyers publishes a symbol file per exchange segment
(https://public.fyers.in/sym_details/<NAME>.csv, no header row). The columns
used here, confirmed against the live files:

    [9]  symbol ticker   "NSE:BANKNIFTY26NOVFUT"   ← what the quote call takes
    [12] scrip code      "61466"                   ← the EXCHANGE's own token

A Zerodha `instrument_token` carries the same exchange token in its upper
bits (`instrument_token >> 8`) and the Zerodha segment in its low byte. So we
match on exchange + exchange token — never by parsing contract names, which
the two brokers spell differently.

The map lives in one Redis hash shared by every worker, field
"<our exchange>:<exchange token>" → Fyers ticker. One worker rebuilds it per
day (Redis lock); until the first build finishes, checks say "not checked".
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging

from app.core.redis_client import get_redis
from app.services import fyers_service
from app.utils.background import fire_and_forget
from app.utils.time_utils import now_ist

logger = logging.getLogger(__name__)

SYMBOL_FILE_URL = "https://public.fyers.in/sym_details/{name}.csv"

#: Fyers file → the `Instrument.exchange` value our Zerodha rows carry.
FILES: dict[str, str] = {
    "NSE_CM": "NSE",
    "NSE_FO": "NFO",
    "NSE_CD": "CDS",
    "BSE_CM": "BSE",
    "BSE_FO": "BFO",
    "MCX_COM": "MCX",
}

#: Zerodha segment byte (`instrument_token & 0xFF`) for each exchange. A token
#: whose low byte doesn't match (indices are 9, for one) is not a contract
#: Fyers lists under that exchange, so it's skipped rather than mismatched.
_ZERODHA_SEGMENT = {"NSE": 1, "NFO": 2, "CDS": 3, "BSE": 4, "BFO": 5, "MCX": 7}

_COL_TICKER = 9
_COL_SCRIP = 12

_KEY = "fyers:symmap"
_KEY_DATE = "fyers:symmap:date"
_KEY_LOCK = "fyers:symmap:lock"
#: Set after a failed build so every order doesn't retry the download.
_KEY_RETRY = "fyers:symmap:retry_after"


def map_field(exchange: str, token: str) -> str | None:
    """The hash field for one of our instruments, or None when the token is
    not a Zerodha contract on an exchange Fyers covers (crypto, forex, an
    Infoway code, an index)."""
    seg = _ZERODHA_SEGMENT.get(str(exchange or "").upper())
    if seg is None:
        return None
    try:
        t = int(str(token))
    except (TypeError, ValueError):
        return None
    if t <= 0 or (t & 0xFF) != seg:
        return None
    return f"{str(exchange).upper()}:{t >> 8}"


async def lookup(exchange: str, token: str) -> tuple[str | None, str | None]:
    """(fyers_symbol, reason). Exactly one of the two is set; `(None, None)`
    means "not a contract Fyers covers — don't record a check at all"."""
    field = map_field(exchange, token)
    if field is None:
        return None, None
    r = get_redis()
    built_on = await r.get(_KEY_DATE)
    if built_on != now_ist().date().isoformat() and not await r.exists(_KEY_RETRY):
        fire_and_forget(refresh(), label="fyers_symbol_map_refresh")
    sym = await r.hget(_KEY, field)
    if sym:
        return str(sym), None
    if not built_on:
        return None, "Fyers symbol list still loading"
    return None, "No Fyers symbol for this contract"


def _parse_file(raw: bytes, exch: str) -> dict[str, str]:
    """One Fyers symbol file → {"<exch>:<exchange token>": ticker}.
    Pure CPU, no I/O — called from a worker thread by `refresh`."""
    out: dict[str, str] = {}
    for row in csv.reader(io.StringIO(raw.decode("utf-8", errors="replace"))):
        if len(row) <= _COL_SCRIP:
            continue
        ticker = row[_COL_TICKER].strip()
        scrip = row[_COL_SCRIP].strip()
        if ":" not in ticker or not scrip.isdigit():
            continue
        out[f"{exch}:{int(scrip)}"] = ticker
    return out


async def refresh(*, force: bool = False) -> int:
    """Download every Fyers symbol file and swap the Redis hash in one step.
    Returns the number of symbols stored (0 if another worker holds the lock
    or today's map is already built)."""
    r = get_redis()
    today = now_ist().date().isoformat()
    if not force and await r.get(_KEY_DATE) == today:
        return 0
    if not await r.set(_KEY_LOCK, "1", nx=True, ex=600):
        return 0
    tmp = f"{_KEY}:building"
    try:
        await r.unlink(tmp)
        total = 0
        c = await fyers_service.http_client()
        for name, exch in FILES.items():
            try:
                resp = await c.get(SYMBOL_FILE_URL.format(name=name), timeout=60.0)
                resp.raise_for_status()
            except Exception:  # noqa: BLE001 — one missing file mustn't lose the rest
                logger.warning("fyers_symbol_file_failed name=%s", name, exc_info=True)
                continue
            # Parsing NSE_FO alone (~90k rows) is ~0.3 s of pure CPU. Done
            # on the event loop it would stall every request, the pending-
            # order poller and the risk loop in this worker for that long,
            # so it runs in a thread and only the Redis writes come back.
            parsed = await asyncio.to_thread(_parse_file, resp.content, exch)
            items = list(parsed.items())
            for i in range(0, len(items), 5000):
                await r.hset(tmp, mapping=dict(items[i : i + 5000]))
            total += len(items)
        if total == 0:
            logger.warning("fyers_symbol_map_empty — keeping the previous map")
            await r.unlink(tmp)
            await r.set(_KEY_RETRY, "1", ex=300)
            return 0
        # UNLINK frees yesterday's 150k-field hash in a Redis background
        # thread; a plain DEL / RENAME-over-it frees it inline and stalls
        # Redis (live prices included) for ~0.1 s.
        await r.unlink(_KEY)
        await r.rename(tmp, _KEY)
        await r.set(_KEY_DATE, today)
        logger.info("fyers_symbol_map_built symbols=%d", total)
        return total
    finally:
        await r.delete(_KEY_LOCK)
