"""Three user-reported bugs in a row, all the same shape: search silently
dropped a contract that should have been listed.

    TCS26NOV...        listed instead of 29 Sep — the cap ran on the rows the
                       search had already kept, and alphabetically "NOV" sorts
                       ahead of "SEP", so the survivors were all November and
                       November looked like the nearest expiry.

    NIFTY 22 Sep       inside the admin's window yet unreachable — ranking is
                       alphabetical, so all 30 rows that fit the panel were
                       15 Sept and the second expiry never appeared.

    NIFTY26SEPFUT      gone entirely — futures and options were indexed under
                       one expiry list per root, so NIFTY's weekly options
                       (15/22 Sep) crowded out its monthly future (29 Sep).
                       Every other index has monthly options, so only NIFTY
                       vanished.

Each was found by a person looking at the app. This file states the invariants
instead, over a fixture shaped like the real NFO catalog, and drives the ACTUAL
filter chain — `_make_expiry_gate` then `_spread_across_expiries` — rather than
re-implementing it.

The invariants:

    1. every underlying that has matching contracts appears in the result
    2. each (underlying, cycle) shows its OWN nearest expiry
    3. every expiry inside the cap is reachable, not just the first
    4. nothing beyond the cap is listed

Bug 3 breaks 1 and 2, bug 1 breaks 2 and 4, bug 2 breaks 3.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.api.v1.user.instruments import _make_expiry_gate, _spread_across_expiries


def _d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# The live catalog's actual shape: NIFTY runs weekly options against monthly
# futures, every other index and every stock runs monthly for both.
W1, W2, W3, W4 = _d(6), _d(13), _d(20), _d(27)      # NIFTY option weeklies
M1, M2, M3 = _d(20), _d(48), _d(75)                  # monthly cycle

SPEC = {
    "NIFTY": {"FUT": [M1, M2, M3], "OPT": [W1, W2, W3, W4]},
    "BANKNIFTY": {"FUT": [M1, M2, M3], "OPT": [M1, M2, M3]},
    "FINNIFTY": {"FUT": [M1, M2, M3], "OPT": [M1, M2, M3]},
    "TCS": {"FUT": [M1, M2, M3], "OPT": [M1, M2, M3]},
}
STRIKES = list(range(20000, 20000 + 50 * 40, 50))  # 40 strikes, like a real ladder


def _catalog() -> list[dict]:
    rows: list[dict] = []
    for root, cycles in SPEC.items():
        for e in cycles["FUT"]:
            rows.append(
                {"name": root, "expiry": e, "instrumentType": "FUT",
                 "exchange": "NFO", "symbol": f"{root}{e.replace('-','')}FUT"}
            )
        for e in cycles["OPT"]:
            for k in STRIKES:
                for t in ("CE", "PE"):
                    rows.append(
                        {"name": root, "expiry": e, "instrumentType": t,
                         "exchange": "NFO", "symbol": f"{root}{e.replace('-','')}{k}{t}"}
                    )
    # Dump order is arbitrary; alphabetical ranking is what the endpoint
    # applies, and it is what made a later expiry sort ahead of a nearer one.
    rows.sort(key=lambda r: r["symbol"])
    return rows


class _FakeZerodha:
    def __init__(self, rows):
        self._instruments_cache = {"NFO": rows}


def _run(kinds, cap, limit=30):
    """The real chain: gate, then rank, then spread. `kinds` picks the chip."""
    rows = [r for r in _catalog() if r["instrumentType"] in kinds]
    gate = _make_expiry_gate(_FakeZerodha(_catalog()), lambda root, ex: cap)
    kept = [
        r for r in rows
        if gate(r["instrumentType"], r["name"], r["exchange"], r["expiry"])
    ]
    kept.sort(key=lambda r: r["symbol"])  # the endpoint's ranking
    return _spread_across_expiries(
        kept, limit, get_root=lambda r: r["name"], get_exp=lambda r: r["expiry"]
    )


def _allowed(root: str, cycle: str, cap: int) -> list[str]:
    return SPEC[root][cycle][:cap]


# ── 1. nothing disappears ───────────────────────────────────────────────────

def test_every_underlying_survives_the_futures_chip():
    out = _run(("FUT",), cap=2)
    assert {r["name"] for r in out} == set(SPEC)


def test_every_underlying_survives_the_options_chip():
    out = _run(("CE", "PE"), cap=2, limit=60)
    assert {r["name"] for r in out} == set(SPEC)


# ── 2. each cycle shows its own nearest ─────────────────────────────────────

def test_each_root_lists_its_own_nearest_future():
    # The NIFTY26SEPFUT bug: a weekly option cycle must not hide a monthly
    # future that is the nearest contract of its own cycle.
    out = _run(("FUT",), cap=2)
    for root in SPEC:
        got = {r["expiry"] for r in out if r["name"] == root}
        assert SPEC[root]["FUT"][0] in got, f"{root} lost its nearest future"


def test_each_root_lists_its_own_nearest_option():
    out = _run(("CE", "PE"), cap=2, limit=60)
    for root in SPEC:
        got = {r["expiry"] for r in out if r["name"] == root}
        assert SPEC[root]["OPT"][0] in got, f"{root} lost its nearest option expiry"


# ── 3. every expiry inside the cap is reachable ─────────────────────────────

def test_the_second_expiry_is_reachable_not_just_the_first():
    # The NIFTY 22 Sept bug: inside the window, but ranking filled the panel
    # with the first expiry so it could never be added.
    out = _run(("CE", "PE"), cap=2, limit=60)
    nifty = {r["expiry"] for r in out if r["name"] == "NIFTY"}
    assert nifty == set(_allowed("NIFTY", "OPT", 2))


# ── 4. nothing beyond the cap ───────────────────────────────────────────────

def test_no_contract_past_the_cap_is_ever_listed():
    # The TCS November bug: the third expiry must not appear at cap 2.
    for kinds, cycle, limit in ((("FUT",), "FUT", 30), (("CE", "PE"), "OPT", 60)):
        out = _run(kinds, cap=2, limit=limit)
        for r in out:
            assert r["expiry"] in _allowed(r["name"], cycle, 2), (
                f"{r['symbol']} is past the cap"
            )


def test_a_cap_of_one_is_exactly_one_expiry_per_cycle():
    out = _run(("FUT",), cap=1)
    for root in SPEC:
        got = {r["expiry"] for r in out if r["name"] == root}
        assert got == {SPEC[root]["FUT"][0]}


# ── the chain must not depend on dump order ─────────────────────────────────

def test_reversing_the_catalog_changes_nothing():
    # Ranking is alphabetical and the pool is gathered in dump order, so a
    # result that depends on dump order is a latent version of all three bugs.
    a = {r["symbol"] for r in _run(("FUT",), cap=2)}
    rows = list(reversed(_catalog()))
    gate = _make_expiry_gate(_FakeZerodha(rows), lambda root, ex: 2)
    kept = [
        r for r in rows
        if r["instrumentType"] == "FUT"
        and gate(r["instrumentType"], r["name"], r["exchange"], r["expiry"])
    ]
    kept.sort(key=lambda r: r["symbol"])
    b = {
        r["symbol"]
        for r in _spread_across_expiries(
            kept, 30, get_root=lambda r: r["name"], get_exp=lambda r: r["expiry"]
        )
    }
    assert a == b
