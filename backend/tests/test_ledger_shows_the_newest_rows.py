"""The ledger window keeps TODAY, not the day it started.

A busy account writes thousands of wallet rows a month. Sorting the window
ascending and then cutting at `limit` handed back the OLDEST rows, so the page
stopped days before today and looked like nothing had happened since.
"""

from __future__ import annotations

import inspect

from app.api.v1.user import ledger as user_ledger


def _src() -> str:
    return inspect.getsource(user_ledger.ledger)


def test_it_reads_newest_first_then_cuts():
    s = _src()
    assert 'sort("-created_at").limit(limit)' in s
    assert 'sort("+created_at")' not in s, "ascending + limit drops today's rows"


def test_the_balances_still_bracket_the_window():
    """Rows now arrive newest → oldest, so the first closes and the last opens.
    Getting this backwards would flip the summary cards."""
    s = _src()
    close = s.index("if closing is None:")
    assert "opening = float(str(t.balance_before))" in s
    assert close < s.index("opening = float(str(t.balance_before))")
    # opening must NOT be latched on the first row any more
    assert "if opening is None:" not in s


def test_a_clipped_window_says_so():
    assert '"truncated": len(out) >= limit' in _src()


def test_the_games_ledger_was_already_newest_first():
    from app.services.games import wallet_service

    assert 'sort("-created_at")' in inspect.getsource(wallet_service.list_ledger)
