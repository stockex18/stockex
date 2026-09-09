"""Re-sync instrument rows whose token Zerodha has since recycled.

Zerodha reuses `instrument_token` numbers across expiries. Token 12094466 was
NIFTY2672822300CE (28-Jul-2026 weekly); expiry-cleanup retired our row the
morning after that contract died, and Kite has since handed the same number to
NIFTY2691522300CE (15-Sep-2026).

`get_by_token` now re-resolves a retired row on demand, which fixes the order
path. It does NOT fix DISPLAY: the trade card, the watchlist and search read
the stored row straight out of Mongo, so a live NIFTY contract kept printing
"28 JUL" under its name until somebody happened to place an order on it.

This script closes that gap in one pass. It touches instrument METADATA only -
expiry, symbol, lot size, strike, tick size, tradable flags. No position, no
trade, no wallet row is read or written.

    cd backend && source .venv/bin/activate
    python -m scripts.resync_recycled_instruments            # report only
    python -m scripts.resync_recycled_instruments --apply    # write

Safe to re-run. A row is rewritten only when the live catalog carries a
DIFFERENT expiry for its token, so a correct row is never touched, and a token
the catalog no longer knows is left exactly as it is.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from app.core.database import init_database
from app.models.instrument import Instrument
from app.services import instrument_service
from app.services.zerodha_service import zerodha

EXCHANGES = ("NSE", "NFO", "BFO", "MCX", "BSE")


async def _catalog() -> dict[str, dict]:
    """token -> catalog row, across every exchange dump we cache."""
    out: dict[str, dict] = {}
    for ex in EXCHANGES:
        try:
            rows = await zerodha.fetch_instruments(ex)
        except Exception as e:  # noqa: BLE001 — one bad dump must not stop the rest
            print(f"  ! {ex}: {e}")
            continue
        for r in rows:
            tok = str(r.get("token") or "")
            if tok:
                out[tok] = r
        print(f"  {ex}: {len(rows)} rows")
    return out


async def _no_subscribe(*_a, **_kw) -> None:
    """Stands in for the ticker subscribe during a bulk run. See main()."""
    return None


def _expiry_of(row: dict) -> dt.date | None:
    raw = row.get("expiry")
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


async def main(apply: bool) -> None:
    await init_database()
    print("Loading Zerodha catalog…")
    cat = await _catalog()
    print(f"  total {len(cat)} tokens\n")

    # The on-demand heal re-subscribes a relisted token so it gets live ticks.
    # That is right for one contract a user just tapped; doing it thousands of
    # times in a loop would flood the ticker pool mid-session and could push it
    # past Zerodha's per-connection token cap. Metadata only here — the tokens
    # people actually watch are subscribed by the normal path.
    zerodha.subscribe_tokens_on_demand = _no_subscribe  # type: ignore[method-assign]

    today = dt.date.today()
    scanned = stale = fixed = dead = 0

    async for inst in Instrument.find_all():
        scanned += 1
        row = cat.get(str(inst.token))
        if row is None:
            continue
        cat_exp = _expiry_of(row)
        if cat_exp is None or cat_exp == inst.expiry:
            continue
        stale += 1
        if cat_exp < today:
            # Catalog itself is carrying a dead contract (dump not yet rolled).
            # Leave the row alone rather than stamping a past expiry onto it.
            dead += 1
            continue
        print(
            f"  {inst.token:>10}  {inst.symbol:<24} {inst.expiry} -> {cat_exp}"
            f"  (tradable {inst.is_tradable} -> True)"
        )
        if apply:
            # Reuse the service's own heal rather than hand-copying fields.
            # It rewrites symbol, display name, lot size, strike and tick
            # size too — a stub row (symbol == token, expiry None) needs all
            # of them, and a half-copy here would drift from the on-demand
            # path the moment either changes.
            await instrument_service._mirror_from_zerodha(
                str(inst.token), existing=inst
            )
        fixed += 1

    print(
        f"\nscanned={scanned}  expiry_mismatch={stale}  "
        f"{'rewritten' if apply else 'would_rewrite'}={fixed}  skipped_dead={dead}"
    )
    if not apply and fixed:
        print("Dry run. Re-run with --apply to write.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    asyncio.run(main(ap.parse_args().apply))
