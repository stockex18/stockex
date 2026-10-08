"""Company / instrument logos, fetched once from public symbol-logo CDNs and
served from our own origin (``GET /api/v1/market/logo/{symbol}``).

No exchange or broker API publishes logos. Two public CDNs cover nearly every
Indian symbol between them:

1. Dhan — keyed directly by NSE symbol. Tried first; covers most of them.
2. TradingView — keyed by a company slug ("logoid") that has to be resolved
   through its symbol search first. EXACT symbol match only: for a delisted or
   renamed ticker the first fuzzy hit is a DIFFERENT company, and a confidently
   wrong logo is worse than no logo — a user cannot tell a wrong one from a
   right one.

Indices, commodities, currencies and crypto have no company behind them, so
they are mapped by hand to TradingView logoids and checked BEFORE any stock
source: a stock CDN has either nothing for "NIFTY" or, worse, a stock that
happens to share the name.

The browser never talks to a vendor. One place to change the source, one cache,
and a vendor blocking us costs a row of initials instead of broken images.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

#: Real symbols carry & and - (M&M, BAJAJ-AUTO). Anything else never reaches a
#: filesystem path — this is the path-traversal guard.
SYMBOL_RE = re.compile(r"^[A-Z0-9&_-]{1,24}$")

#: On disk, not in memory, so every gunicorn worker shares it. Relative to
#: backend/ like uploads/; a deploy is a `git pull`, which leaves it alone.
CACHE_DIR = Path("symbol_logos")
MAX_AGE_SEC = 24 * 3600
#: A vendor that did not answer is not a vendor that said "no logo".
RETRY_AFTER_SEC = 10 * 60
MAX_SVG_BYTES = 200_000

DHAN_URL = "https://s3tv-symbol.dhan.co/symbols/{}.svg"
TV_SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/v3/"
TV_LOGO_URL = "https://s3-symbol-logo.tradingview.com/{}.svg"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "image/svg+xml",
}

# Every spelling our screens use, spaces removed (see `normalize`).
_INDICES = {
    **dict.fromkeys(["NIFTY", "NIFTY50"], "indices/nifty-50"),
    **dict.fromkeys(["BANKNIFTY", "NIFTYBANK"], "indices/nifty-bank-index"),
    **dict.fromkeys(
        ["FINNIFTY", "NIFTYFINSERVICE", "NIFTYFINSERV"], "indices/nifty-financial-services-index"
    ),
    **dict.fromkeys(["MIDCPNIFTY", "NIFTYMIDSELECT", "NIFTYMIDCAPSELECT"], "indices/nifty-midcap"),
    **dict.fromkeys(["NIFTYNXT50", "NIFTYNEXT50", "NIFTYJR"], "indices/nifty-next-50-index"),
    **dict.fromkeys(["NIFTYIT", "CNXIT"], "indices/nifty-it-index"),
    "NIFTY500": "indices/nifty-500",
    "INDIAVIX": "indices/india-vix",
    "SENSEX": "indices/bse-sensex",
    **dict.fromkeys(["SPX500", "US500", "SPX"], "indices/s-and-p-500"),
    **dict.fromkeys(["NAS100", "US100", "NDX"], "indices/nasdaq-100"),
    **dict.fromkeys(["US30", "DJI"], "indices/dow-30"),
    "UK100": "indices/uk-100",
    **dict.fromkeys(["DE40", "GER40", "DAX"], "indices/dax"),
    **dict.fromkeys(["JPN225", "JP225"], "indices/nikkei-225"),
    "HK50": "indices/hang-seng",
    "FRA40": "indices/cac-40",
    "EU50": "indices/euro-stoxx-50",
    "AUS200": "indices/asx-200",
}

_COMMODITIES = {
    **dict.fromkeys(["GOLD", "GOLDM", "GOLDPETAL", "GOLDGUINEA", "GOLDTEN", "XAUUSD", "XAU"], "metal/gold"),
    **dict.fromkeys(["SILVER", "SILVERM", "SILVERMIC", "XAGUSD", "XAG"], "metal/silver"),
    **dict.fromkeys(["XPTUSD", "PLATINUM"], "metal/platinum"),
    **dict.fromkeys(["XPDUSD", "PALLADIUM"], "metal/palladium"),
    "COPPER": "metal/copper",
    **dict.fromkeys(["ZINC", "ZINCMINI"], "metal/zinc"),
    **dict.fromkeys(["LEAD", "LEADMINI"], "metal/lead"),
    **dict.fromkeys(["ALUMINIUM", "ALUMINI"], "metal/aluminum"),
    "NICKEL": "metal/nickel",
    **dict.fromkeys(["CRUDEOIL", "CRUDEOILM", "USOIL", "UKOIL", "WTI", "BRENT"], "crude-oil"),
    **dict.fromkeys(["NATURALGAS", "NATGASMINI", "NATGAS"], "natural-gas"),
}

# Currency → the flag TradingView draws for it. A pair shows its base currency.
_FLAGS = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "AUD": "AU", "CAD": "CA",
    "CHF": "CH", "NZD": "NZ", "INR": "IN", "CNH": "CN", "CNY": "CN", "SGD": "SG",
    "HKD": "HK", "ZAR": "ZA", "SEK": "SE", "NOK": "NO", "MXN": "MX", "TRY": "TR",
}

# NIFTY25OCTFUT, NIFTY25OCT25000CE (monthly) and NIFTY25O1425000CE (weekly:
# year, month as 1-9/O/N/D, day). Every contract shares its underlying's logo.
_FNO = re.compile(r"^([A-Z&-][A-Z0-9&-]*?)\d{2}(?:[A-Z]{3}|[1-9OND]\d{2})(?:FUT|\d+(?:CE|PE))$")
_CRYPTO_OPT = re.compile(r"^([A-Z0-9]+)-\d{6}-\d+-[CP]$")  # BTC-260922-76000-C
_CRYPTO_PAIR = re.compile(r"^([A-Z0-9]{2,10}?)(?:USDT|USDC|USD)$")
_LOGOID_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,80}$", re.I)

_PROLOG = re.compile(r"^\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*", re.S)
_DANGER = re.compile(
    r"<\s*(?:[\w-]+:)?(?:script|foreignobject|iframe|embed|object)\b"
    r"|javascript:"
    r"|(?<![\w.-])on[a-z]+\s*=",
    re.I,
)


def normalize(raw: str) -> str | None:
    """The cache key for a symbol, or None when it is not a symbol at all.

    Validated BEFORE anything else — it becomes a file name."""
    sym = re.sub(r"\s+", "", str(raw or "")).upper()
    if not SYMBOL_RE.match(sym):
        return None
    m = _CRYPTO_OPT.match(sym)
    if m:
        return f"{m.group(1)}USD"
    m = _FNO.match(sym)
    return m.group(1) if m else sym


def fixed_logoid(key: str) -> str | None:
    """Hand-mapped logo for something that is not a company, else None."""
    if key in _INDICES:
        return _INDICES[key]
    if key in _COMMODITIES:
        return _COMMODITIES[key]
    if len(key) == 6 and key[:3] in _FLAGS and key[3:] in _FLAGS:
        return f"country/{_FLAGS[key[:3]]}"
    m = _CRYPTO_PAIR.match(key)
    if m and m.group(1) not in _FLAGS:
        return f"crypto/XTVC{m.group(1)}"
    return None


def is_safe_svg(body: bytes) -> bool:
    """True only for a plain SVG with nothing that can run.

    It is served from OUR origin, so script inside it would run with our
    privileges — the CSP on the response is the second line, this is the first.
    """
    if not body or len(body) > MAX_SVG_BYTES:
        return False
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    if _DANGER.search(text):
        return False
    # XML prolog and comments may come first ("<!-- by TradingView -->");
    # a DOCTYPE may not, which also rules out entity tricks.
    rest = text[_PROLOG.match(text).end():]
    return re.match(r"<svg[\s>/]", rest) is not None


def pick_logoid(payload: object, symbol: str) -> str | None:
    """The logoid of the search hit whose symbol is EXACTLY `symbol`.

    Never the first fuzzy hit. A country flag or sector icon is TradingView's
    "no logo" placeholder and counts as nothing."""
    hits = payload.get("symbols") if isinstance(payload, dict) else payload
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict):
            continue
        if re.sub(r"</?em>", "", str(hit.get("symbol") or "")).upper() != symbol:
            continue
        logoid = hit.get("logoid")
        if (
            isinstance(logoid, str)
            and _LOGOID_RE.match(logoid)
            and not logoid.startswith(("country/", "sector/"))
        ):
            return logoid
    return None


async def _svg(client: httpx.AsyncClient, url: str) -> bytes | None:
    r = await client.get(url)
    if r.status_code != 200:
        return None
    return r.content if is_safe_svg(r.content) else None


async def _fetch(key: str) -> bytes | None:
    """None = every source answered and none has it. Raises when one didn't answer."""
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=_HEADERS) as client:
        fixed = fixed_logoid(key)
        if fixed:
            # Not a company: never fall through to a stock CDN.
            return await _svg(client, TV_LOGO_URL.format(fixed))
        body = await _svg(client, DHAN_URL.format(quote(key, safe="")))
        if body:
            return body
        r = await client.get(
            TV_SEARCH_URL,
            params={"text": key, "exchange": "NSE", "search_type": "stocks"},
            headers={"Origin": "https://www.tradingview.com", "Accept": "application/json"},
        )
        if r.status_code != 200:
            return None
        try:
            logoid = pick_logoid(r.json(), key)
        except ValueError:
            return None
        return await _svg(client, TV_LOGO_URL.format(logoid)) if logoid else None


# Disk side, kept sync on purpose: a logo is a few KB on local disk.


def _cached(key: str) -> tuple[bool, bytes | None]:
    """(answered, svg). answered=False means go and ask the vendors."""
    hit = CACHE_DIR / f"{key}.svg"
    if hit.is_file():
        return True, hit.read_bytes()
    # Without this a screen full of unknown names re-hits both vendors on
    # every render.
    marker = CACHE_DIR / f"{key}.missing"
    if marker.is_file() and time.time() - marker.stat().st_mtime < MAX_AGE_SEC:
        return True, None
    return False, None


def _remember(key: str, body: bytes | None, ttl: int = MAX_AGE_SEC) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    marker = CACHE_DIR / f"{key}.missing"
    if body is None:
        # A marker counts for MAX_AGE_SEC from its mtime; backdating it makes
        # it count for only `ttl`.
        marker.touch()
        t = time.time() - MAX_AGE_SEC + ttl
        os.utime(marker, (t, t))
        return
    # .partial then rename: a concurrent reader never sees half a file.
    partial = CACHE_DIR / f"{key}.{os.getpid()}.partial"
    partial.write_bytes(body)
    os.replace(partial, CACHE_DIR / f"{key}.svg")
    marker.unlink(missing_ok=True)


async def get_logo(raw: str) -> tuple[bytes | None, int]:
    """(svg, cache seconds). svg is None when there is no logo to show."""
    key = normalize(raw)
    if key is None:
        return None, MAX_AGE_SEC
    answered, body = _cached(key)
    if answered:
        return body, MAX_AGE_SEC
    try:
        body = await _fetch(key)
    except httpx.HTTPError as exc:
        logger.info("symbol_logo_vendor_unreachable key=%s err=%s", key, type(exc).__name__)
        _remember(key, None, RETRY_AFTER_SEC)
        return None, RETRY_AFTER_SEC
    _remember(key, body)
    return body, MAX_AGE_SEC
