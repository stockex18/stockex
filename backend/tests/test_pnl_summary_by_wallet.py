"""The P&L summary splits Today / This week / Last week per trading wallet.

Client request: show each wallet's P&L (NSE / BSE, MCX, Crypto, Forex) on its
own. A trade or position counts in the wallet its money moved in
(`wallet_kind_for_segment`, the wallet router's rule), and the four wallets
always add up to the overall totals.

The database and the price feed are replaced with fakes; no Mongo / Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as Ns

import pytest

from app.api.v1.user import positions as pos_api
from app.services import market_data_service, position_service

USD_INR = 90.0


class _Query:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self):
        return self._rows


def _trade(segment: str, pnl_inr: float, charges: float, executed_at: datetime):
    return Ns(
        instrument=Ns(segment=segment),
        pnl_inr=str(pnl_inr),
        total_charges=str(charges),
        brokerage="0",
        executed_at=executed_at,
    )


def _position(segment_type: str, avg: float, ltp: float, qty: float):
    return Ns(
        segment_type=segment_type,
        instrument=Ns(segment=segment_type, token=f"tok-{segment_type}"),
        avg_price=str(avg),
        ltp=str(ltp),
        quantity=qty,
        realized_pnl="0",
        open_usd_inr_rate=None,
    )


@pytest.fixture
def fake_db(monkeypatch):
    now = datetime.now(UTC)
    last_week = now - timedelta(days=8)
    trades = [
        # today
        _trade("NSE_INDEX_OPTION_BUY", 1000, 50, now),
        _trade("NSE_EQUITY", -200, 10, now),
        _trade("MCX_FUTURE", 500, 20, now),
        _trade("CRYPTO_SPOT", -300, 0, now),
        _trade("FOREX", 150, 5, now),
        # last week only
        _trade("MCX_FUTURE", -400, 0, last_week),
    ]
    open_positions = [
        _position("NSE_EQUITY", 100, 110, 10),  # +100
        _position("CRYPTO_SPOT", 50, 51, 2),  # +2 (Infoway prices count as INR)
    ]

    def fake_trade_find(query):
        rng = query["executed_at"]
        return _Query(
            [
                t
                for t in trades
                if t.executed_at >= rng["$gte"] and ("$lt" not in rng or t.executed_at < rng["$lt"])
            ]
        )

    async def fake_ltp(_token):
        return 0

    async def fake_refresh(_p, _ltp):
        return None

    monkeypatch.setattr(pos_api.Trade, "find", staticmethod(fake_trade_find))
    monkeypatch.setattr(pos_api.Position, "find", staticmethod(lambda _q: _Query(open_positions)))
    monkeypatch.setattr(market_data_service, "get_display_ltp", fake_ltp)
    monkeypatch.setattr(market_data_service, "get_usd_inr_rate", lambda: USD_INR)
    monkeypatch.setattr(position_service, "refresh_unrealized_pnl", fake_refresh)
    monkeypatch.setattr(pos_api, "_effective_qty", lambda p: (float(p.quantity), 1.0, 1))
    pos_api._PNL_SUMMARY_CACHE.clear()
    yield
    pos_api._PNL_SUMMARY_CACHE.clear()


async def _summary():
    user = Ns(id="u-pnl-by-wallet")
    return (await pos_api.positions_pnl_summary(user)).data


async def test_each_wallet_gets_its_own_pnl(fake_db):
    by = (await _summary())["by_wallet"]

    assert set(by) == {"NSE_BSE", "MCX", "CRYPTO", "FOREX"}
    # NSE / BSE: (1000 - 50) + (-200 - 10) realised, +100 open
    assert by["NSE_BSE"]["today_realised"] == 740
    assert by["NSE_BSE"]["open_unrealised"] == 100
    assert by["NSE_BSE"]["today_pnl"] == 840
    # MCX: 500 - 20 today; last week's -400 stays out of today
    assert by["MCX"]["today_pnl"] == 480
    assert by["MCX"]["last_week_pnl"] == -400
    # Crypto: -300 realised, +2 open
    assert by["CRYPTO"]["today_pnl"] == -298
    # Forex
    assert by["FOREX"]["today_pnl"] == 145


async def test_wallets_add_up_to_the_totals(fake_db):
    d = await _summary()
    for field in ("today_pnl", "today_realised", "open_unrealised", "week_pnl", "last_week_pnl"):
        assert round(sum(w[field] for w in d["by_wallet"].values()), 2) == d[field], field
