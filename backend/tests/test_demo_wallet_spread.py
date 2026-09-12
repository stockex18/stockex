"""A demo account's credit has to land where it can be spent.

Trading runs off the four segment wallets and the games run off the games
wallet, so 🪙5,00,000 sitting in main left a demo user looking at money they
could not trade with. Operator: "1-1 lakh saare wallet me add kar do, game
and all 4 wallet".
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.services import demo_service, wallet_kinds


@pytest.fixture
def moves(monkeypatch):
    """Record every transfer the spread makes."""
    done: list[tuple[str, Decimal]] = []
    fail: set[str] = set()

    async def transfer(_uid, from_kind, to_kind, amount):
        if to_kind in fail:
            raise RuntimeError("wallet unavailable")
        assert from_kind == wallet_kinds.MAIN
        done.append((to_kind, Decimal(str(amount))))

    async def to_games(_uid, amount):
        if "GAMES" in fail:
            raise RuntimeError("games wallet unavailable")
        done.append(("GAMES", Decimal(str(amount))))
        return {}

    from app.services import segment_wallet_service
    from app.services.games import wallet_service as games_wallet

    monkeypatch.setattr(segment_wallet_service, "transfer", transfer)
    monkeypatch.setattr(games_wallet, "transfer_main_to_games", to_games)
    return done, fail


def test_one_lakh_into_each_of_the_four_wallets_and_games(moves):
    done, _ = moves
    out = asyncio.run(demo_service.spread_demo_funds("u1"))
    assert [k for k, _ in done] == [*wallet_kinds.SEGMENT_KINDS, "GAMES"]
    assert {a for _, a in done} == {Decimal("100000")}
    # Five wallets × 1 lakh = the whole 5,00,000 demo credit.
    assert sum(a for _, a in done) == Decimal("500000")
    assert set(out) == {*wallet_kinds.SEGMENT_KINDS, "GAMES"}


def test_there_are_exactly_four_segment_wallets():
    assert len(wallet_kinds.SEGMENT_KINDS) == 4


def test_one_wallet_failing_does_not_cost_the_others(moves):
    done, fail = moves
    fail.add(wallet_kinds.MCX)
    out = asyncio.run(demo_service.spread_demo_funds("u1"))
    assert wallet_kinds.MCX not in out
    assert "GAMES" in out and wallet_kinds.CRYPTO in out
    assert sum(a for _, a in done) == Decimal("400000")


def test_the_share_is_configurable(moves):
    done, _ = moves
    asyncio.run(demo_service.spread_demo_funds("u1", Decimal("250")))
    assert {a for _, a in done} == {Decimal("250")}
