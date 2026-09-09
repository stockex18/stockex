"""The expiry cap must be exactly the number the admin typed.

Operator, on the live admin page: "jo admin set karu wahi dikhe — 1, 2, 3, 4".
The number is a count of EXPIRIES, not of months. NIFTY set to 2 means the
nearest two contract dates; NSE set to 1 means one, for every instrument on
that exchange whose per-script box is blank.

The field is labelled "Show expiry month", which is what led me to read it as
a month window - 1 would then have meant all four September weeklies. It does
not. The label is the odd one out; the number is contracts.

Two real defects were fixed alongside it:

  - the cap only ever ran on FUTURES, so the option chain honoured the number
    while the "NSE OPT" search chip listed every expiry on the board. One
    setting, two answers, and a user could reach a contract the chain hid.

  - options in the Mongo search path grouped on `Instrument.name`, which is
    the composed "NIFTY 11AUG26 24900 CE". Keyed on that, every strike is its
    own underlying and nothing is ever trimmed.
"""

from __future__ import annotations

import inspect
from datetime import date

from app.api.v1.user import instruments as inst_mod
from app.api.v1.user.option_chain import _limit_to_expiries as cap

NIFTY = [
    date(2026, 9, 15),
    date(2026, 9, 22),
    date(2026, 9, 29),
    date(2026, 10, 6),
    date(2026, 10, 13),
    date(2026, 10, 27),
]


def test_the_number_is_a_count_of_expiries():
    assert cap(NIFTY, 1) == NIFTY[:1]
    assert cap(NIFTY, 2) == NIFTY[:2]   # current + next, nothing else
    assert cap(NIFTY, 4) == NIFTY[:4]


def test_weeklies_are_not_collapsed_into_a_month():
    # 2 on a weekly board is two Tuesdays, not all of September.
    assert cap(NIFTY, 2) == [date(2026, 9, 15), date(2026, 9, 22)]


def test_a_missing_or_zero_setting_still_yields_one():
    assert cap(NIFTY, 0) == NIFTY[:1]
    assert cap(NIFTY, None) == NIFTY[:1]


def test_asking_for_more_than_exists_is_not_an_error():
    assert cap(NIFTY, 99) == NIFTY
    assert cap([], 3) == []


def test_strings_work_as_well_as_dates():
    # The search path carries "YYYY-MM-DD" strings, the chain carries dates.
    assert cap(["2026-09-15", "2026-09-22", "2026-10-06"], 2) == [
        "2026-09-15",
        "2026-09-22",
    ]


def test_the_search_panel_trims_options_too_not_only_futures():
    assert '_DATED = ("FUT", "CE", "PE")' in inspect.getsource(inst_mod)
    src = inspect.getsource(inst_mod._cap_by_expiry_window)
    assert "_DATED" in src
    assert "_limit_to_expiries" in src


def test_options_are_grouped_by_underlying_not_by_display_name():
    src = inspect.getsource(inst_mod)
    assert "_mongo_root = lambda i:" in src
    assert "get_root=_mongo_root" in src


def test_the_chain_and_the_search_share_one_helper():
    # Two copies of "nearest N" is how the panels drifted apart last time.
    assert "_limit_to_expiries" in inspect.getsource(inst_mod._cap_by_expiry_window)
