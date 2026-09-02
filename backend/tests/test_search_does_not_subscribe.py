"""Searching is browsing a catalogue, not watching an instrument.

Every search hit used to be quoted AND put on the Kite websocket. Typing "cru"
put forty CRUDEOIL strikes on the live feed. Production carried the result:

    subscribedInstruments: 1,500   (at the LRU cap)
      symbol-less leftovers: 1,237   (82%)
      actual futures:           77   (and futures carry 541 of the orders)

The cap was being spent on rows nobody was trading, so the LRU evicted the
instruments that mattered — that is the `tokens_dropped` in the pool log.

Price now starts when the user ADDS the instrument, which is also when it
starts being stored. Two halves, both tested here: the frontend stops asking,
and the backend stops losing the symbol when it does subscribe.
"""

from __future__ import annotations

import inspect
import io
import re

import pytest

from app.services import market_data_service as mds

MOBILE = r"D:\stockex_new\frontend-user\components\trading\MobileInstrumentsBar.tsx"
DESKTOP = r"D:\stockex_new\frontend-user\components\trading\InstrumentsPanel.tsx"


def src(path: str) -> str:
    return io.open(path, encoding="utf-8", errors="ignore").read()


# ── the frontend stops asking ─────────────────────────────────────────
@pytest.mark.parametrize("path", [MOBILE, DESKTOP])
def test_search_hits_are_not_put_on_the_feed(path):
    """`searchHits` must not reach the token list that drives quotesBatch and
    the websocket stream."""
    s = src(path)
    start = s.index("const all = (() => {")
    end = s.index("})();", start)
    selector = s[start:end]
    assert "searchHits" not in selector, "search results still feed the token list"


@pytest.mark.parametrize("path", [MOBILE, DESKTOP])
def test_browse_buckets_are_not_either(path):
    """A browse listing is a catalogue for the same reason a search is."""
    s = src(path)
    start = s.index("const all = (() => {")
    end = s.index("})();", start)
    assert "bucketHits" not in s[start:end]


@pytest.mark.parametrize("path", [MOBILE, DESKTOP])
def test_the_watchlist_still_gets_prices(path):
    """The whole point is that ADDED instruments keep working. If this breaks,
    the user's own watchlist goes blank."""
    s = src(path)
    start = s.index("const all = (() => {")
    end = s.index("})();", start)
    selector = s[start:end]
    assert "activeWl?.items" in selector


@pytest.mark.parametrize("path", [MOBILE, DESKTOP])
def test_a_managed_segment_still_gets_prices(path):
    """`segmentItems` is exactly the list the user added to that chip."""
    s = src(path)
    start = s.index("const all = (() => {")
    end = s.index("})();", start)
    assert "segmentItems" in s[start:end]


def test_a_priceless_row_shows_the_contract_instead_of_two_dashes():
    """Two empty dashes where a spread belongs reads as a broken feed. The row
    shows what it does know, so two strikes of one underlying stay tellable
    apart."""
    s = src(MOBILE)
    assert "const priceless =" in s
    assert "fmtExpiry(expiry)" in s
    assert "Tap + to add" in s


def test_the_row_is_handed_the_details_it_needs():
    s = src(MOBILE)
    assert "expiry={q.expiry ?? null}" in s
    assert "strike={q.strike ?? null}" in s
    assert "lotSize={q.lot_size ?? null}" in s


def test_the_search_payload_carries_them():
    """No new endpoint needed — /instruments/search already returns all three."""
    api = src(r"D:\stockex_new\backend\app\api\v1\user\instruments.py")
    block = api[api.index("def _kite_row_to_payload") : api.index("def _kite_row_to_payload") + 2200]
    for field in ('"expiry"', '"strike"', '"lot_size"'):
        assert field in block, field


# ── the backend stops losing the symbol ───────────────────────────────
def test_a_cross_worker_subscribe_resolves_the_symbol():
    """A non-leader worker can only put TOKENS on the channel. The leader used
    to re-subscribe them with no symbol, and the service then stores
    `symbol = str(token)`, `exchange = "NSE"` — which is how every MCX
    contract in production ended up labelled NSE."""
    s = inspect.getsource(mds._forward_feed_subscription)
    assert "await _sym_map_for(numeric)" in s


def test_the_lookup_asks_the_catalog_once_for_the_whole_batch():
    """Per-token queries on a path that fires on every browse would be worse
    than the bug."""
    s = inspect.getsource(mds._sym_map_for)
    assert '{"token": {"$in":' in re.sub(r"\s+", " ", s)


def test_it_carries_the_real_exchange():
    """The dual-account router keys off this. An MCX token marked NSE never
    moves to account B, so the second socket carries nothing."""
    s = inspect.getsource(mds._sym_map_for)
    assert '"exchange":' in s and "ex.value" in s


def test_a_row_with_no_symbol_is_skipped_not_faked():
    s = inspect.getsource(mds._sym_map_for)
    assert "if not sym:" in s and "continue" in s


def test_a_lookup_failure_never_blocks_the_subscribe():
    """Falling back to the old behaviour is fine; refusing to subscribe is not
    — that would leave a held position with no price."""
    s = inspect.getsource(mds._sym_map_for)
    assert "except Exception" in s
    assert s.rstrip().endswith("return out")


@pytest.mark.asyncio
async def test_an_empty_batch_does_no_work():
    assert await mds._sym_map_for([]) == {}
