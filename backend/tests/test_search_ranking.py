"""A chip-filtered search never ranked anything.

Two operator screenshots. Typing "t" under NSE EQ returned NIFTY 50, NIFTY
MIDCAP 100, NIFTY BANK, NIFTY 100, NIFTY DIV OPPS 50 ... and typing "ta"
returned GSFC and SBIN ABOVE TATACHEM.

The MongoDB path has been tiered since the "NIFTY pick kiya aur kisi aur ka
rate dikha" report - exact symbol, prefix, contains, and a NAME match last
because it is the weakest signal. But selecting a chip sends the request down a
different path entirely: a raw scan of the Zerodha cache that kept the first
`limit` rows containing the term anywhere in symbol OR name, in whatever order
the dump happens to be in. No tiers ran at all.

    "ta"  ->  GSFC   name "GUJ STATE FERT & CHEM"   matched, listed early
              SBIN   name "State Bank of India"     matched, listed early
              TATACHEM                              matched, listed later

And NSE indices arrive from Kite as ordinary EQ rows - NIFTY 50, NIFTY BANK,
INDIA VIX - so "NIFTY" containing a T meant one letter filled the list with
them. Measured on the live catalog: 88 of 11,626 active NSE_EQUITY rows carry a
space in the tradingsymbol, and every one is an index. Not one real company.
"""

from __future__ import annotations

import inspect

from app.api.v1.user.instruments import _search_rank


def order(rows, q):
    return [r["symbol"] for r in sorted(rows, key=lambda r: _search_rank(r, q))]


NSE = "NSE"
ROWS = [
    {"symbol": "NIFTY 50", "name": "NIFTY 50", "exchange": NSE},
    {"symbol": "NIFTY TATA 25 CAP", "name": "NIFTY TATA 25 CAP", "exchange": NSE},
    {"symbol": "GSFC", "name": "GUJ STATE FERT & CHEM", "exchange": NSE},
    {"symbol": "SBIN", "name": "State Bank of India", "exchange": NSE},
    {"symbol": "TATACHEM", "name": "TATA CHEMICALS", "exchange": NSE},
    {"symbol": "TATAINVEST", "name": "TATA INVESTMENT", "exchange": NSE},
    {"symbol": "TATASTEEL", "name": "TATA STEEL", "exchange": NSE},
]


# ── the reported orderings ────────────────────────────────────────────
def test_real_tata_stocks_come_before_a_name_match():
    got = order(ROWS, "TA")
    assert got.index("TATACHEM") < got.index("GSFC")
    assert got.index("TATASTEEL") < got.index("SBIN")


def test_indices_sink_below_every_stock():
    got = order(ROWS, "TA")
    assert got[-1] == "NIFTY 50"
    assert got.index("NIFTY TATA 25 CAP") > got.index("TATAINVEST")


def test_an_exact_symbol_wins():
    got = order(ROWS, "SBIN")
    assert got[0] == "SBIN"


def test_a_prefix_beats_a_contains():
    rows = [
        {"symbol": "TATACHEM", "name": "TATA CHEMICALS", "exchange": NSE},
        {"symbol": "XTATAY", "name": "SOMETHING", "exchange": NSE},
    ]
    assert order(rows, "TATA")[0] == "TATACHEM"


def test_a_name_only_match_is_last_among_stocks():
    rows = [
        {"symbol": "GSFC", "name": "GUJ STATE FERT & CHEM", "exchange": NSE},
        {"symbol": "STAR", "name": "STAR LTD", "exchange": NSE},
    ]
    assert order(rows, "STA")[0] == "STAR"


def test_the_shorter_symbol_breaks_a_tie():
    """Between two contains-matches, the tighter one is the likelier intent."""
    rows = [
        {"symbol": "TATASTEELLONG", "name": "x", "exchange": NSE},
        {"symbol": "TATASTEEL", "name": "x", "exchange": NSE},
    ]
    assert order(rows, "TATA")[0] == "TATASTEEL"


# ── indices stay reachable ────────────────────────────────────────────
def test_an_index_is_ranked_not_removed():
    """Typing it must still find it - NSE indices have no chip of their own,
    so filtering them out would make NIFTY 50 unfindable anywhere."""
    got = order([{"symbol": "NIFTY 50", "name": "NIFTY 50", "exchange": NSE}], "NIFTY 50")
    assert got == ["NIFTY 50"]


def test_only_indian_exchanges_use_the_space_rule():
    """The space test is a fact about NSE/BSE tradingsymbols. A spaced symbol
    on another feed is not evidence of anything."""
    a = _search_rank({"symbol": "GOLD SPOT", "name": "x", "exchange": "CDS"}, "GOLD")
    b = _search_rank({"symbol": "GOLDX", "name": "x", "exchange": "CDS"}, "GOLD")
    assert a[0] == b[0] == 0


# ── the scan now collects enough to rank ──────────────────────────────
def test_the_scan_gathers_a_pool_before_cutting():
    """Cutting at `limit` inside the loop is what made it unrankable - the 30
    rows kept were the 30 the dump listed first, so the best match might never
    be collected at all."""
    from app.api.v1.user import instruments as api

    src = inspect.getsource(api)
    assert "_POOL = max(limit, 400)" in src
    assert "if len(collected) >= _POOL:" in src
    assert "collected.sort(key=lambda r: _search_rank(r, q_upper))" in src
    # The cut to `limit` now happens inside _spread_across_expiries, which
    # takes the rows round-robin across expiries instead of the first N in
    # rank order - one expiry used to fill the whole panel. Still a cut, and
    # still after the pool is gathered and ranked.
    assert "collected = _spread_across_expiries(" in src
    i_pool = src.index("_POOL = max(limit, 400)")
    i_cut = src.index("collected = _spread_across_expiries(")
    assert i_pool < i_cut


def test_ranking_is_skipped_when_there_is_no_query():
    """Browsing a chip with an empty box is a listing, not a search."""
    from app.api.v1.user import instruments as api

    src = inspect.getsource(api)
    i = src.index("collected.sort(key=lambda r: _search_rank(r, q_upper))")
    assert "if q_upper:" in src[i - 120 : i]
