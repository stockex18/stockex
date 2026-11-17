"""The user ledger pages through any date window, newest first.

The Ledger page used to load only the last month (max 1,000 entries), so a
user could see older trades in Reports ("All time") that the Ledger never
showed. The endpoint now takes `skip` + `limit`, returns the window's `total`,
and works out opening / closing balance and the settlement total over the
whole window rather than just the page shown.

The database is replaced with a fake; no Mongo / Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as Ns

import pytest

from app.api.v1.user import ledger as ledger_api
from app.models.transaction import TransactionType

START = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
USER = "u-ledger"


def _txn(i: int, ttype=TransactionType.CHARGES, amount=-10.0, user=USER):
    # Balance falls by 10 per entry, starting at 10,000.
    before = 10_000 - 10 * i
    return Ns(
        id=f"t{i:03d}",
        user_id=user,
        created_at=START + timedelta(days=i),
        transaction_type=ttype,
        amount=str(amount),
        balance_before=str(before),
        balance_after=str(before + amount),
        description="",
        reference_type="ORDER",
        reference_id=f"o{i}",
    )


# 60 entries, one a day from 1 Sep; two of them are settlement bookings.
ROWS = [_txn(i) for i in range(60)]
ROWS[5] = _txn(5, TransactionType.SETTLEMENT_OUTSTANDING_BOOKED, -10.0)
ROWS[40] = _txn(40, TransactionType.SETTLEMENT_OUTSTANDING_BOOKED, -10.0)
ROWS.append(_txn(0, user="someone-else"))


def _match(t, q) -> bool:
    if t.user_id != q["user_id"]:
        return False
    rng = q.get("created_at", {})
    if "$gte" in rng and t.created_at < rng["$gte"]:
        return False
    if "$lte" in rng and t.created_at > rng["$lte"]:
        return False
    return not ("transaction_type" in q and t.transaction_type.value != q["transaction_type"])


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, key):
        return _Query(sorted(self._rows, key=lambda t: t.created_at, reverse=key.startswith("-")))

    def skip(self, n):
        return _Query(self._rows[n:])

    def limit(self, n):
        return _Query(self._rows[:n])

    async def to_list(self):
        return self._rows

    async def count(self):
        return len(self._rows)


class _FakeTxn:
    @staticmethod
    def find(q):
        return _Query([t for t in ROWS if _match(t, q)])


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    monkeypatch.setattr(ledger_api, "WalletTransaction", _FakeTxn)
    monkeypatch.setattr(ledger_api, "_sanitize_narration", lambda t: t.description)


async def _get(**kw):
    args = {"from_date": None, "to_date": None, "limit": 200, "skip": 0, **kw}
    return (await ledger_api.ledger(Ns(id=USER), **args)).data


async def test_all_time_reaches_the_oldest_entry():
    d = await _get(limit=25, skip=50)
    assert d["total"] == 60
    assert len(d["rows"]) == 10
    assert d["rows"][-1]["id"] == "t000"  # the very first entry is reachable


async def test_pages_run_newest_first_without_gaps():
    seen = []
    for skip in range(0, 60, 25):
        d = await _get(limit=25, skip=skip)
        seen += [r["id"] for r in d["rows"]]
    assert seen == [f"t{i:03d}" for i in range(59, -1, -1)]


async def test_balances_and_settlement_cover_the_whole_window():
    d = await _get(limit=5, skip=0)  # only the 5 newest on this page
    assert d["closing_balance"] == 10_000 - 10 * 60  # after the newest entry
    assert d["opening_balance"] == 10_000  # before the oldest entry
    assert d["total_settlement_booked"] == 20  # both bookings, though off this page
    assert d["truncated"] is True


async def test_date_window_limits_the_entries():
    d = await _get(from_date=START + timedelta(days=10), to_date=START + timedelta(days=19, hours=1))
    assert d["total"] == 10
    assert [r["id"] for r in d["rows"]][0] == "t019"
    assert d["opening_balance"] == 10_000 - 10 * 10
    assert d["truncated"] is False


async def test_other_users_entries_never_show():
    d = await _get()
    assert d["total"] == 60
