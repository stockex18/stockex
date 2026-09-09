"""Search showed TCS November options while the cap was set to one expiry.

Operator screenshot: NSE OPT chip, query "tcs", every row TCS26NOV (23 Nov).
TCS expires 29 Sep, 27 Oct, 23 Nov and the NSE fallback was 1, so only 29 Sep
should have been listed.

The cap was applied to the SURVIVORS of the search instead of to the catalog,
and by then the survivors were already the wrong ones:

    the cache scan stops at a 400-row pool in dump order, ranking then sorts
    alphabetically, and "TCS26NOV..." sorts ahead of "TCS26OCT..." and
    "TCS26SEP...". Every row that reached the cap was November, so November
    looked like the nearest expiry and the whole month was let through.

Deriving the window from rows can only ever be right when the rows are the
complete set, which on a search path they never are. The gate now reads the
full catalog for the underlying and runs INSIDE the scan, so the pool fills
with contracts that are already inside the window.

The number itself is a count of EXPIRIES, not months: "jo admin set karu wahi
dikhe - 1, 2, 3, 4". NIFTY 2 is the nearest two contract dates.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

from app.api.v1.user import instruments as inst_mod
from app.api.v1.user.option_chain import _limit_to_expiries as cap

NIFTY = [
    date(2026, 9, 15),
    date(2026, 9, 22),
    date(2026, 9, 29),
    date(2026, 10, 6),
]


def test_the_number_is_a_count_of_expiries():
    assert cap(NIFTY, 1) == NIFTY[:1]
    assert cap(NIFTY, 2) == NIFTY[:2]   # current + next, nothing else
    assert cap(NIFTY, 4) == NIFTY[:4]


def test_weeklies_are_not_collapsed_into_a_month():
    assert cap(NIFTY, 2) == [date(2026, 9, 15), date(2026, 9, 22)]


def test_a_missing_or_zero_setting_still_yields_one():
    assert cap(NIFTY, 0) == NIFTY[:1]
    assert cap(NIFTY, None) == NIFTY[:1]


def test_asking_for_more_than_exists_is_not_an_error():
    assert cap(NIFTY, 99) == NIFTY
    assert cap([], 3) == []


# ── the gate ────────────────────────────────────────────────────────────────

def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()

SEP, OCT, NOV = _future(20), _future(48), _future(75)


class _FakeZerodha:
    """Just the attribute the gate reads: the raw per-exchange dumps."""

    def __init__(self, rows):
        self._instruments_cache = {"NFO": rows}


TCS_ROWS = [
    {"name": "TCS", "expiry": e, "instrumentType": t, "exchange": "NFO"}
    for e in (SEP, OCT, NOV)
    for t in ("CE", "PE", "FUT")
]


def _gate(cap_n: int, rows=TCS_ROWS):
    return inst_mod._make_expiry_gate(_FakeZerodha(rows), lambda root, ex: cap_n)


def test_november_is_rejected_when_only_the_nearest_expiry_is_allowed():
    # The reported bug, from the other side: a November row must fail the gate
    # even when it is the only expiry the caller has in hand.
    g = _gate(1)
    assert g("CE", "TCS", "NFO", SEP) is True
    assert g("CE", "TCS", "NFO", OCT) is False
    assert g("CE", "TCS", "NFO", NOV) is False


def test_the_window_comes_from_the_catalog_not_from_the_rows_in_hand():
    # Two expiries allowed: September and October pass, November does not —
    # regardless of what the search happened to collect.
    g = _gate(2)
    assert [g("PE", "TCS", "NFO", e) for e in (SEP, OCT, NOV)] == [True, True, False]


def test_futures_and_options_share_one_window():
    g = _gate(1)
    assert g("FUT", "TCS", "NFO", SEP) is True
    assert g("FUT", "TCS", "NFO", NOV) is False


def test_undated_rows_pass_untouched():
    g = _gate(1)
    assert g("EQ", "TCS", "NSE", None) is True
    assert g(None, "TCS", "NSE", None) is True


def test_an_expired_contract_is_never_the_nearest():
    past = (date.today() - timedelta(days=5)).isoformat()
    rows = [{"name": "TCS", "expiry": past, "instrumentType": "CE", "exchange": "NFO"}]
    rows += [{"name": "TCS", "expiry": SEP, "instrumentType": "CE", "exchange": "NFO"}]
    g = _gate(1, rows)
    assert g("CE", "TCS", "NFO", SEP) is True
    assert g("CE", "TCS", "NFO", past) is False


def test_it_fails_open_for_a_root_the_catalog_does_not_carry():
    # Infoway crypto / forex rows never appear in a Kite dump. No opinion must
    # never blank a panel.
    g = _gate(1)
    assert g("CE", "BTCUSD", "NFO", SEP) is True


def test_the_gate_runs_inside_the_scan_not_after_the_cut():
    # Applied after the pool is cut it can only re-confirm whatever survived,
    # which is exactly how November got through.
    src = inspect.getsource(inst_mod.search)
    assert src.index("if not _kite_in_window(inst):") < src.index("collected.sort(")


def test_options_are_grouped_by_underlying_not_by_display_name():
    # `Instrument.name` is the composed "NIFTY 11AUG26 24900 CE"; keyed on
    # that, every strike is its own underlying and nothing is ever trimmed.
    src = inspect.getsource(inst_mod)
    assert "_mongo_root = lambda i:" in src
    assert "_mongo_root(i)" in src
