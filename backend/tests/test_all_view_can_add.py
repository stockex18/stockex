"""A row in the mobile "All" view can be added to its own segment.

"All" was added so a phone could search across segments. The rows it shows
had a favourite star and nothing else, and the operator asked for an Add
button — because on this platform Add is what starts a price. A search result
is a catalogue row and carries none (that rule exists: typing "cru" once put
forty CRUDEOIL strikes on the live feed and ate 1,237 of 1,500 subscription
slots). Adding to a managed chip is what puts an instrument on the feed.

The obstacle: Add posts to `/marketwatch/segment/{name}/items`, and the mobile
bar took `{name}` from the SELECTED chip. In All there is no chip. So the row
has to say which segment it belongs to.

That name is NOT `netting_service._seg_name_for`, which looks like the obvious
tool and is not. It answers "which admin SETTINGS row governs an order" — it
splits NSE futures and options into STK/IDX rows the watchlist has no concept
of, and it takes this platform's canonical segment names where a search row
carries Kite's raw ones. Using it would have produced names the add endpoint
rejects with a 400.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from app.api.v1.user import instruments as inst
from app.api.v1.user.instruments import managed_row_for
from app.api.v1.user.marketwatch import _ALLOWED_SEG_NAMES

_MOBILE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend-user" / "components" / "trading" / "MobileInstrumentsBar.tsx"
)


# ── the mapping ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "exchange,itype,expected",
    [
        ("NSE", "EQ", "NSE_EQ"),
        ("BSE", "EQ", "BSE_EQ"),
        ("NFO", "FUT", "NSE_FUT"),
        ("NFO", "CE", "NSE_OPT"),
        ("NFO", "PE", "NSE_OPT"),
        ("BFO", "FUT", "BSE_FUT"),
        ("BFO", "CE", "BSE_OPT"),
        ("MCX", "FUT", "MCX_FUT"),
        ("MCX", "PE", "MCX_OPT"),
    ],
)
def test_each_indian_instrument_maps_to_its_chip(exchange, itype, expected):
    assert managed_row_for(exchange, itype) == expected


def test_case_does_not_matter():
    assert managed_row_for("nfo", "fut") == "NSE_FUT"


def test_a_plain_equity_with_no_type_is_still_equity():
    """Kite leaves the type blank on some cash rows."""
    assert managed_row_for("NSE", "") == "NSE_EQ"


@pytest.mark.parametrize(
    "exchange,itype",
    [("CRYPTO", "SPOT"), ("FOREX", ""), ("INDICES", ""), ("NSE", "FUT"), ("", ""), (None, None)],
)
def test_anything_that_is_not_a_managed_chip_has_no_row(exchange, itype):
    """Crypto, forex, indices, stocks and commodities have nothing to add to —
    they are non-managed chips — and a malformed row must not guess."""
    assert managed_row_for(exchange, itype) is None


def test_every_name_it_can_return_is_one_the_add_endpoint_accepts():
    """The whole reason the helper exists. A name outside this set is a 400."""
    produced = {
        managed_row_for(ex, it)
        for ex in ("NSE", "BSE", "NFO", "BFO", "MCX")
        for it in ("EQ", "FUT", "CE", "PE", "")
    } - {None}
    assert produced, "helper returned nothing"
    assert produced <= _ALLOWED_SEG_NAMES, produced - _ALLOWED_SEG_NAMES


def test_and_every_name_the_endpoint_accepts_is_reachable():
    """Otherwise a managed chip exists that no search row can ever be added to."""
    produced = {
        managed_row_for(ex, it)
        for ex in ("NSE", "BSE", "NFO", "BFO", "MCX")
        for it in ("EQ", "FUT", "CE")
    } - {None}
    assert produced == set(_ALLOWED_SEG_NAMES)


# ── it reaches the client ─────────────────────────────────────────────
def test_the_kite_row_payload_carries_it():
    src = inspect.getsource(inst._kite_row_to_payload)
    assert '"managed_row": managed_row_for(' in src


def test_the_mongo_row_payload_carries_it():
    """Two builders feed /instruments/search; a row from either one has to
    answer, or Add works for some results and silently not for others."""
    src = inspect.getsource(inst)
    assert src.count('"managed_row": managed_row_for(') == 2


def test_the_obvious_wrong_mapper_is_not_used():
    src = inspect.getsource(managed_row_for)
    assert "_seg_name_for" not in src.replace("`netting_service._seg_name_for`", "")


# ── the mobile bar uses it ────────────────────────────────────────────
def _mobile() -> str:
    return _MOBILE.read_text(encoding="utf-8", errors="ignore")


def test_the_add_handler_takes_the_rows_own_segment():
    s = _mobile()
    assert "async function addToSegment(token: string, symbol: string, row?: string | null)" in s
    assert "MarketwatchAPI.addSegmentItem(seg, token)" in s


def test_all_resolves_the_target_segment_from_the_row():
    s = _mobile()
    assert 'bucket?.mode === "all" ? (q.managed_row ?? null)' in s


def test_all_offers_add_rather_than_the_browse_star_and_remove_pair():
    """A remove X in All would need its own segment plumbed through too, and
    All is a catalogue — it adds."""
    s = _mobile()
    assert 'const addMode = inSearchMode || bucket?.mode === "all"' in s
    assert "if (addMode && !alreadyAdded)" in s


def test_already_added_is_read_per_segment_not_for_one_chip():
    """All has no single chip to ask. It asks only for the segments actually
    on screen, not all eight, and shares the cache key with the managed chips
    so adding from either side updates the other."""
    s = _mobile()
    assert "useQueries(" in s
    assert 'queryKey: ["segment-items", r]' in s
    assert "addedInAllView.has(token)" in s


def test_the_all_view_still_does_not_subscribe_or_price_its_rows():
    """Deliberate and unchanged. A search result is a catalogue row; price
    starts when the instrument is ADDED, and shows under its chip. Putting
    these on the feed is what ate 1,237 of 1,500 subscription slots."""
    s = _mobile()
    start = s.index("const all = (() => {")
    selector = s[start : s.index("})();", start)]
    assert 'bucket?.mode === "all"' not in selector
