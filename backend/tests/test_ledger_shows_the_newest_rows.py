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
    assert 'sort("-created_at").skip(skip).limit(limit)' in s
    # Ascending order is only used to find the single oldest entry (for the
    # opening balance), never to cut a page — that dropped today's rows.
    assert s.count('sort("+created_at")') == s.count('sort("+created_at").limit(1)')


def test_the_balances_still_bracket_the_window():
    """The newest entry closes the window and the oldest opens it — over the
    whole window, not just the page shown (see test_ledger_paging.py).
    Getting this backwards would flip the summary cards."""
    s = _src()
    assert "closing = float(str(newest[0].balance_after))" in s
    assert "opening = float(str(oldest[0].balance_before))" in s


def test_a_clipped_window_says_so():
    assert '"truncated": skip + len(out) < total' in _src()


def test_the_games_ledger_was_already_newest_first():
    from app.services.games import wallet_service

    assert 'sort("-created_at")' in inspect.getsource(wallet_service.list_ledger)
