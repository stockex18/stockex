"""Positions and Active Trades must show the SAME current price and P&L.

Reported: on the terminal the Positions tab and the Active Trades tab showed a
different "current" for the same open trade, so two different P&Ls. Two
causes: the backend marked Active Trades at the last traded price while
positions mark at the close side (bid for a long, ask for a short), and the
terminal moved Positions with the live stream while Active Trades waited for a
2 s poll. One rule now (`close_side_mark`) and one stream.
"""

import asyncio
import pathlib

import pytest

import app.services.market_data_service as mds
from app.services import position_service as ps

ROOT = pathlib.Path(__file__).resolve().parents[2]


def run(c):
    return asyncio.run(c)


QUOTE = {"ltp": 1155.12, "bid": 1155.00, "ask": 1155.30}


def test_a_long_closes_at_the_bid():
    assert float(run(ps.close_side_mark("738561", True, 1155.12, QUOTE))) == 1155.00


def test_a_short_closes_at_the_ask():
    assert float(run(ps.close_side_mark("738561", False, 1155.12, QUOTE))) == 1155.30


@pytest.mark.parametrize("quote", [{"ltp": 1155.12}, {"bid": 0, "ask": "0"}, {"bid": None}])
def test_without_that_side_it_is_the_last_price(quote):
    assert float(run(ps.close_side_mark("738561", True, 1155.12, quote))) == 1155.12


def test_a_quote_that_fails_keeps_the_last_price(monkeypatch):
    async def boom(token):
        raise RuntimeError("feed down")

    monkeypatch.setattr(mds, "get_quote", boom)
    assert float(run(ps.close_side_mark("738561", True, 1155.12))) == 1155.12


def test_positions_and_active_trades_share_the_one_rule():
    svc = (ROOT / "backend/app/services/position_service.py").read_text(encoding="utf-8")
    refresh = svc[svc.index("async def refresh_unrealized_pnl") :][:3000]
    assert "await close_side_mark(" in refresh

    api = (ROOT / "backend/app/api/v1/user/positions.py").read_text(encoding="utf-8")
    active = api[api.index("async def list_active_trades") :]
    assert "position_service.close_side_mark(" in active
    assert "ltp = mark_by_side.get(" in active


def test_the_terminal_moves_both_tabs_with_the_same_stream():
    src = (ROOT / "frontend-user/components/trading/PositionsTabs.tsx").read_text(encoding="utf-8")
    assert "for (const p of [...positions, ...(activeTrades ?? [])])" in src
    row = src[src.index("<ActiveTradeRow") :][:600]
    assert "liveMark={liveCloseSide({" in row
    fn = src[src.index("function ActiveTradeRow(") :][:2500]
    assert "const ltp = liveMark && liveMark > 0 ? liveMark : serverMark;" in fn
    assert "const displayPnl = basePnl + markShift;" in fn
