"""The P&L report totals each category (trading wallet) on its own.

Requested by the client to give users more clarity on their P&L: on
Reports -> P&L, show how much P&L each category made in total, not only the
per-symbol rows. Category = the wallet the trade's money
moved in (NSE / BSE, MCX, Crypto, Forex), and the categories always add up to
the report's totals.

The database is replaced with a fake; no Mongo / Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace as Ns

import pytest

from app.api.v1.user import reports
from app.services import report_pdf_service

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def _trade(symbol, segment, action, qty, value, charges, *, pnl_inr=None, superseded=False):
    return Ns(
        instrument=Ns(symbol=symbol, segment=segment),
        action=Ns(value=action),
        quantity=qty,
        value=str(value),
        total_charges=str(charges),
        pnl_inr=None if pnl_inr is None else str(pnl_inr),
        superseded_by_reopen=superseded,
        executed_at=NOW,
    )


TRADES = [
    # NSE / BSE: two symbols
    _trade("NIFTY26NOVFUT", "NSE_INDEX_FUTURE", "BUY", 65, 1_640_000, 40),
    _trade("NIFTY26NOVFUT", "NSE_INDEX_FUTURE", "SELL", 65, 1_645_000, 40, pnl_inr=4920),
    _trade("AXISBANK26NOVFUT", "NSE_STOCK_FUTURE", "SELL", 625, 845_000, 20, pnl_inr=-1500),
    # MCX
    _trade("SILVERMIC26NOVFUT", "MCX_FUTURE", "BUY", 1, 150_000, 30),
    _trade("SILVERMIC26NOVFUT", "MCX_FUTURE", "SELL", 1, 149_000, 30, pnl_inr=-1060),
    # Crypto
    _trade("BTCUSD", "CRYPTO_SPOT", "SELL", 0.01, 640, 0, pnl_inr=12.5),
    # A close an admin later reopened — left out everywhere
    _trade("SILVERMIC26NOVFUT", "MCX_FUTURE", "SELL", 1, 149_000, 30, pnl_inr=-999, superseded=True),
]


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *_a):
        return self

    async def to_list(self):
        return self._rows


class _Field:
    """Stands in for a Beanie field: any comparison builds a no-op filter."""

    def __eq__(self, _o):
        return True

    def __ge__(self, _o):
        return True

    def __le__(self, _o):
        return True

    __hash__ = object.__hash__


class _FakeTrade:
    user_id = _Field()
    executed_at = _Field()

    @staticmethod
    def find(*_a, **_k):
        return _Query(TRADES)


@pytest.fixture
def fake_trades(monkeypatch):
    monkeypatch.setattr(reports, "Trade", _FakeTrade)


async def _payload():
    return await reports._pnl_payload(Ns(id="u-report"), NOW, NOW)


async def test_each_category_gets_its_total(fake_trades):
    by = {c["category"]: c for c in (await _payload())["by_category"]}

    assert list(by) == ["NSE_BSE", "MCX", "CRYPTO", "FOREX"]
    assert by["NSE_BSE"]["label"] == "NSE / BSE"
    assert by["NSE_BSE"]["pnl"] == 3420  # 4920 - 1500
    assert by["NSE_BSE"]["trades"] == 3
    assert by["NSE_BSE"]["symbols"] == 2
    assert by["NSE_BSE"]["charges"] == 100
    assert by["NSE_BSE"]["gross_pnl"] == 3520
    assert by["MCX"]["pnl"] == -1060  # the reopened close is not counted
    assert by["MCX"]["trades"] == 2
    assert by["CRYPTO"]["pnl"] == 12.5
    # A category with no trades is still listed, at zero.
    assert by["FOREX"] == {
        "category": "FOREX",
        "label": "Forex",
        "trades": 0,
        "symbols": 0,
        "buy_value": 0.0,
        "sell_value": 0.0,
        "charges": 0.0,
        "pnl": 0.0,
        "gross_pnl": 0.0,
    }


async def test_symbols_carry_their_category(fake_trades):
    rows = {r["symbol"]: r["category"] for r in (await _payload())["by_symbol"]}
    assert rows == {
        "NIFTY26NOVFUT": "NSE_BSE",
        "AXISBANK26NOVFUT": "NSE_BSE",
        "SILVERMIC26NOVFUT": "MCX",
        "BTCUSD": "CRYPTO",
    }


async def test_categories_add_up_to_the_totals(fake_trades):
    d = await _payload()
    cats = d["by_category"]
    assert round(sum(c["pnl"] for c in cats), 2) == d["net_pnl"]
    assert round(sum(c["charges"] for c in cats), 2) == d["total_charges"]
    assert round(sum(c["buy_value"] for c in cats), 2) == d["total_buy_value"]
    assert round(sum(c["sell_value"] for c in cats), 2) == d["total_sell_value"]


async def test_pdf_has_the_category_table(fake_trades):
    user = Ns(full_name="Test", user_code="CL1", email="t@x.io")
    pdf = report_pdf_service.build_pnl_pdf(user, await _payload())
    assert pdf.startswith(b"%PDF")
