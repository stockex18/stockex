"""A demo account opens with money in every wallet it can spend from.

Operator: "Demo account main wallet balance 5 lac, other 5 wallet 1 lac each —
sare NSE, MCX, forex, crypto and games me 1L rahega demo me login hote saath
hi."

The old code credited 🪙5,00,000 and then transferred all five lakh out into
the five spendable wallets, so main finished at ZERO. It also funded the
shared "Try Demo" account only at provisioning, so the second visitor found
whatever the first had left behind.
"""

from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import demo_service, wallet_kinds

LAKH = Decimal("100000")


@pytest.fixture
def books(monkeypatch):
    """A fake set of wallets: balances in, transfers and credits recorded."""
    state = {
        "segment": {k: Decimal("0") for k in wallet_kinds.SEGMENT_KINDS},
        "games": Decimal("0"),
        "main": Decimal("0"),
        "fail": set(),
    }
    moves: list[tuple[str, Decimal]] = []
    credits: list[Decimal] = []

    async def seg_get(_uid, kind):
        return SimpleNamespace(available_balance=state["segment"][kind])

    async def seg_transfer(_uid, from_kind, to_kind, amount):
        if to_kind in state["fail"]:
            raise RuntimeError("wallet unavailable")
        assert from_kind == wallet_kinds.MAIN
        moves.append((to_kind, Decimal(str(amount))))

    async def games_balance(_uid):
        return state["games"]

    async def games_transfer(_uid, amount):
        if "GAMES" in state["fail"]:
            raise RuntimeError("games wallet unavailable")
        moves.append(("GAMES", Decimal(str(amount))))
        return {}

    async def main_get(_uid):
        return SimpleNamespace(available_balance=state["main"])

    async def main_adjust(_uid, amount, **_kw):
        credits.append(Decimal(str(amount)))
        return SimpleNamespace()

    from app.services import segment_wallet_service, wallet_service
    from app.services.games import wallet_service as games_wallet

    monkeypatch.setattr(segment_wallet_service, "get_or_create", seg_get)
    monkeypatch.setattr(segment_wallet_service, "transfer", seg_transfer)
    monkeypatch.setattr(games_wallet, "get_balance", games_balance)
    monkeypatch.setattr(games_wallet, "transfer_main_to_games", games_transfer)
    monkeypatch.setattr(wallet_service, "get_or_create", main_get)
    monkeypatch.setattr(wallet_service, "adjust", main_adjust)
    return state, moves, credits


def _fund():
    return asyncio.run(demo_service.ensure_demo_funding("u1"))


def test_a_fresh_demo_gets_five_lakh_in_main_and_one_in_each_of_the_five(books):
    state, moves, credits = books
    out = _fund()

    assert [k for k, _ in moves] == [*wallet_kinds.SEGMENT_KINDS, "GAMES"]
    assert {a for _, a in moves} == {LAKH}
    # Credited once: the five lakh main keeps PLUS the five it hands out.
    assert credits == [Decimal("1000000")]
    assert set(out) == {*wallet_kinds.SEGMENT_KINDS, "GAMES"}


def test_there_are_exactly_four_segment_wallets_beside_games():
    assert len(wallet_kinds.SEGMENT_KINDS) == 4


def test_main_keeps_its_own_five_lakh():
    assert demo_service.DEMO_MAIN_TARGET == Decimal("500000")
    assert demo_service.DEMO_WALLET_SHARE == LAKH


def test_a_wallet_already_full_is_left_alone(books):
    state, moves, credits = books
    state["segment"][wallet_kinds.MCX] = LAKH
    _fund()

    assert wallet_kinds.MCX not in [k for k, _ in moves]
    # Four top-ups of a lakh + the five lakh main still needs.
    assert credits == [Decimal("900000")]


def test_a_half_spent_wallet_is_only_made_good(books):
    state, moves, credits = books
    state["segment"][wallet_kinds.CRYPTO] = Decimal("40000")
    _fund()

    assert (wallet_kinds.CRYPTO, Decimal("60000")) in moves


def test_a_demo_user_who_is_ahead_keeps_the_winnings(books):
    state, moves, credits = books
    state["main"] = Decimal("800000")
    state["games"] = Decimal("250000")
    _fund()

    assert "GAMES" not in [k for k, _ in moves]  # already over target
    # Only the four segment wallets are topped up; main is above target, so
    # nothing extra is credited for it and nothing is taken away.
    assert credits == [Decimal("400000")]


def test_one_wallet_failing_does_not_cost_the_others(books):
    state, moves, _ = books
    state["fail"].add(wallet_kinds.MCX)
    out = _fund()

    assert wallet_kinds.MCX not in out
    assert "GAMES" in out and wallet_kinds.CRYPTO in out
    assert sum(a for _, a in moves) == Decimal("400000")


def test_the_shared_demo_is_refunded_on_every_login():
    from app.services import auth_service

    src = inspect.getsource(auth_service.create_demo_session)
    # Outside the "first-ever provisioning" branch, so visitor two gets it too.
    assert "ensure_demo_funding" in src
    assert src.index("ensure_demo_funding") > src.index("Could not start demo session")


def test_the_personal_demo_signup_uses_the_same_path():
    from app.api.v1.user import auth as user_auth

    assert "ensure_demo_funding" in inspect.getsource(user_auth)


def test_the_daily_reset_funds_through_the_same_path():
    src = inspect.getsource(demo_service.reset_global_demo)
    assert "ensure_demo_funding" in src
