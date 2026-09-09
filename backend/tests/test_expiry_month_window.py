"""'Show expiry month' counted expiry DATES, not months.

Admin screenshot, 9 Sep 2026. NIFTY chip "SHOW EXPIRY MONTH" = 2, per-exchange
NSE = 1. The admin's reading is the one the label states: 1 means "this
month's expiries". What they got was one Tuesday.

NIFTY expires weekly, so September carries 15, 22 and 29 Sept. Counting dates
gives:

    N=1 -> [15 Sep]                       one weekly, not the month
    N=2 -> [15 Sep, 22 Sep]               still September, still short

Counting months gives what the label promises:

    N=1 -> [15, 22, 29 Sep]
    N=2 -> September + October

For monthly contracts - MCX, every futures board we list - a month has exactly
one expiry, so the two readings coincide and nothing changes there. The
difference only ever shows on weeklies, which is precisely where the operator
hit it.

The window is counted over months that ACTUALLY have contracts rather than by
calendar arithmetic from today, so on 30 Sep - when nothing is left to expire
in September - "1 month" means October rather than an empty board.
"""

from __future__ import annotations

import inspect
from datetime import date

from app.api.v1.user import instruments as inst_mod
from app.api.v1.user.option_chain import _limit_to_expiry_months as window

SEP = [date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29)]
OCT = [date(2026, 10, 6), date(2026, 10, 27)]
NOV = [date(2026, 11, 24)]
NIFTY = SEP + OCT + NOV


def test_one_month_is_the_whole_month_not_the_nearest_weekly():
    assert window(NIFTY, 1) == SEP


def test_two_months_reaches_into_the_next_month():
    assert window(NIFTY, 2) == SEP + OCT


def test_monthly_contracts_are_unaffected():
    # One expiry per month — dates and months agree, which is why this went
    # unnoticed on MCX and on the futures board.
    monthly = [date(2026, 9, 29), date(2026, 10, 27), date(2026, 11, 24)]
    assert window(monthly, 1) == monthly[:1]
    assert window(monthly, 2) == monthly[:2]


def test_it_counts_months_that_have_contracts_not_calendar_months():
    # Late September, nothing left to expire this month. "1 month" must mean
    # the next month that has something, not an empty board.
    assert window(OCT + NOV, 1) == OCT


def test_a_missing_or_zero_setting_still_yields_a_month():
    assert window(NIFTY, 0) == SEP
    assert window(NIFTY, None) == SEP


def test_strings_work_as_well_as_dates():
    # The futures-search path carries "YYYY-MM-DD" strings, the chain carries
    # date objects. Both share the sortable YYYY-MM prefix.
    assert window(["2026-09-15", "2026-09-22", "2026-10-06"], 1) == [
        "2026-09-15",
        "2026-09-22",
    ]


def test_empty_in_empty_out():
    assert window([], 3) == []


def test_the_search_panel_trims_options_too_not_only_futures():
    # The chain honoured the month window while the "NSE OPT" chip listed
    # every expiry on the board, so a user could reach a contract the chain
    # deliberately hid.
    src = inspect.getsource(inst_mod._cap_by_expiry_window)
    assert '_DATED = ("FUT", "CE", "PE")' in inspect.getsource(inst_mod)
    assert "_DATED" in src
    assert "_limit_to_expiry_months" in src


def test_options_are_grouped_by_underlying_not_by_display_name():
    # `Instrument.name` is the composed "NIFTY 11AUG26 24900 CE". Keyed on
    # that, every strike is its own underlying and nothing is ever trimmed.
    src = inspect.getsource(inst_mod)
    assert "_mongo_root = lambda i:" in src
    assert "get_root=_mongo_root" in src
