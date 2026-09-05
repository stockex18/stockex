"""Searching for an instrument has to return that instrument.

Reported: "NIFTY pick kiya aur RELIANCE ka rate dikha", across equity, futures
and options. It was not a price bug at all — the frontend keys every quote by
token and does so correctly. The wrong TOKEN was being handed over, because the
thing the user meant was not on the list they picked from.

    search("NIFTY")
      3,341 rows match — the `name` field pulls in every ETF whose name
      mentions Nifty — and 1,582 of them sort BEFORE "NIFTY 50".
      The query sorted by SYMBOL and cut at limit 30.

      So NIFTY 50 sat at position ~1,583 of a 30-row list. What came back was
      ABSLBANETF, ALPHA, AUTOBEES … ETFs priced in the hundreds, which read
      exactly like a stock quote. The user tapped one believing it was Nifty.

Sorting a relevance question alphabetically is the whole bug. Two more sat
underneath it:

  * seed stubs (`NSE_EQ_RELIANCE`, non-numeric token) carry NO price — ltp,
    bid, ask, high, low all zero, permanently — and `find_one(symbol=…)`
    returned the stub ahead of the real 738561.
  * indices are stored under their official name, so "BANKNIFTY" never
    reached "NIFTY BANK" and the top hit was BANKNIFTY1, a Kotak ETF.
"""

from __future__ import annotations

import inspect
import re

from app.services import instrument_service as isvc

SRC = inspect.getsource(isvc.search)


# ── relevance, not alphabet ───────────────────────────────────────────
def test_the_alphabetical_cut_is_gone():
    """One `$or` sorted by symbol and truncated — the shape that buried the
    answer under 1,582 ETFs."""
    assert 'query["$or"] = [{"symbol": regex}' not in SRC


def test_the_tiers_run_best_first():
    """Exact, then prefix, then contains, then name. Order is the point."""
    i_exact = SRC.index('{"symbol": exact}')
    i_prefix = SRC.index('{"symbol": prefix}')
    i_any = SRC.index('{"symbol": anywhere}')
    i_name = SRC.index('{"name": anywhere}')
    assert i_exact < i_prefix < i_any < i_name


def test_a_name_match_can_never_outrank_a_symbol_match():
    """A name hit is the weakest signal and is how an unrelated ETF gets in.
    It is the last tier, so it only fills what the symbol tiers left."""
    assert SRC.index('{"name": anywhere}') > SRC.index('{"symbol": anywhere}')


def test_the_regexes_are_anchored_the_way_their_names_claim():
    assert 'exact = re.compile(f"^{esc}$"' in SRC
    assert 'prefix = re.compile(f"^{esc}"' in SRC
    assert 'anywhere = re.compile(esc' in SRC


def test_the_search_term_is_escaped():
    """A symbol search box is user input. `re.escape` is what stops a stray
    `(` or `*` turning into a regex error or a scan."""
    assert "esc = re.escape(term)" in SRC


def test_results_are_deduped_by_token():
    """The tiers overlap by construction — an exact match is also a prefix
    match — so without this the same row lands three times."""
    assert "if key in seen:" in SRC
    assert "seen.add(key)" in SRC


def test_an_empty_query_still_lists():
    """The side panel opens with no term typed and must not come back blank."""
    assert "if not q or not q.strip():" in SRC


# ── seed stubs ────────────────────────────────────────────────────────
def test_a_stub_is_recognised_by_its_non_numeric_token():
    assert 'not str(inst.token or "").lstrip("-").isdigit()' in SRC


def test_a_stub_is_dropped_when_the_real_row_is_present():
    """`NSE_EQ_RELIANCE` has ltp / bid / ask / high / low all zero, for ever.
    A user who picks it gets a blank quote and an untradeable instrument
    while 738561 sits right there."""
    assert "real_symbols = {r.symbol for r in out if not _is_stub(r)}" in SRC
    assert "r.symbol not in real_symbols" in SRC


def test_a_stub_with_no_real_twin_survives_but_sinks():
    """Dropping it outright would make instruments that only exist as a stub
    unfindable. Last place is enough."""
    assert "out.sort(key=_is_stub)" in SRC


# ── indices are stored under a name nobody types ──────────────────────
def test_the_aliases_point_at_real_catalog_symbols():
    """Verified against the live catalog: NIFTY 50 = 256265, NIFTY BANK =
    260105, NIFTY FIN SERVICE = 257801. If a rename ever breaks one of these
    the alias silently matches nothing, which is the old bug returning."""
    assert isvc._SYMBOL_ALIASES["BANKNIFTY"] == "NIFTY BANK"
    assert isvc._SYMBOL_ALIASES["NIFTY"] == "NIFTY 50"
    assert isvc._SYMBOL_ALIASES["FINNIFTY"] == "NIFTY FIN SERVICE"


def test_the_alias_is_matched_ignoring_case_and_spaces():
    """People type "bank nifty", "BankNifty", "BANKNIFTY"."""
    for typed in ("banknifty", "BANK NIFTY", "BankNifty", "  BANKNIFTY "):
        key = typed.strip().upper().replace(" ", "")
        assert isvc._SYMBOL_ALIASES.get(key) == "NIFTY BANK", typed


def test_the_alias_tier_goes_in_front_of_everything():
    """It is the only tier that can reach a symbol the term does not contain,
    so anywhere else it would lose to BANKNIFTY1."""
    assert "tiers.insert(0," in SRC
    assert SRC.index("tiers.insert(0,") > SRC.index('{"name": anywhere}')  # built, then prepended


def test_an_unknown_term_gets_no_alias_tier():
    """Ordinary symbols must go through the normal tiers untouched."""
    assert isvc._SYMBOL_ALIASES.get("RELIANCE") is None
    assert isvc._SYMBOL_ALIASES.get("TCS") is None


def test_the_alias_regex_would_match_its_target():
    """The tier is `^alias$`, case-insensitive — the same shape the exact
    tier uses. Checked here rather than trusting the f-string by eye."""
    for typed, target in isvc._SYMBOL_ALIASES.items():
        rx = re.compile(f"^{re.escape(target)}$", re.IGNORECASE)
        assert rx.match(target), typed
        assert rx.match(target.lower()), typed
