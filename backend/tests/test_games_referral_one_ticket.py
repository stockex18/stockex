"""Games referral -- the referrer's % of ONE ticket's winning.

What has to hold:

  * with `referrer_base` "ONE_TICKET" (the default), a 5-ticket win pays the
    referrer exactly what a 1-ticket win pays: 5% of one ticket's winning;
  * "FULL_WIN" keeps the old behaviour -- 5% of the whole payout;
  * the first-win-per-game gate still means one payout per game per friend;
  * Bracket gets the same one-ticket rule;
  * a game without a ticket count (Jackpot) still pays on the full winning,
    whatever the setting says;
  * a reversal claws back exactly what was credited;
  * Up/Down and Bracket bets placed before `tickets` was stored still get a
    ticket count.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

from app.models.games.settings import GameConfig
from app.models.user import GameReferralStats
from app.services import referral_service
from app.services.games import referral
from app.utils.decimal_utils import to_decimal128

GAME = "niftyUpDown"
# Live Up/Down economics: ticket 600, multiplier 1.66667, referrer 5%.
ONE_TICKET_WIN = Decimal("1000.00")   # 600 × 1.66667, rounded
FIVE_TICKET_WIN = Decimal("5000.01")  # 3000 × 1.66667


def _run(c):
    return asyncio.run(c)


def _cfg(**kw) -> GameConfig:
    return GameConfig(ticket_price=600.0, win_multiplier=1.66667, referrer_profit_pct=5.0, **kw)


class Player:
    """The referred friend (B). Only the fields the referral code reads."""

    def __init__(self):
        self.id = PydanticObjectId()
        self.user_code = "CL0000001"
        self.referred_by = PydanticObjectId()  # A
        self.game_referral: GameReferralStats | None = None

    async def save(self):
        return self


@pytest.fixture
def paid(monkeypatch):
    """Records what reaches the referrer's games wallet (+ and −)."""
    book: list[Decimal] = []

    async def credit(user_id, amount, **_):
        book.append(Decimal(str(amount)))

    async def debit(user_id, amount, **_):
        book.append(-Decimal(str(amount)))

    async def noop(*_, **__):
        return None

    monkeypatch.setattr(referral.wallet_service, "atomic_games_wallet_credit", credit)
    monkeypatch.setattr(referral.wallet_service, "atomic_games_wallet_debit", debit)
    monkeypatch.setattr(referral.wallet_service, "house_settle", noop)
    monkeypatch.setattr(referral_service, "record_referral_earning", noop)
    return book


def test_five_tickets_pay_the_referrer_the_same_as_one(paid):
    _run(referral.credit_referral_on_win(Player(), FIVE_TICKET_WIN, _cfg(), game_key=GAME, tickets=5))
    _run(referral.credit_referral_on_win(Player(), ONE_TICKET_WIN, _cfg(), game_key=GAME, tickets=1))
    assert paid == [Decimal("50.00"), Decimal("50.00")]


def test_one_ticket_is_the_default():
    assert GameConfig().referrer_base == "ONE_TICKET"


def test_full_win_keeps_the_whole_payout(paid):
    cfg = _cfg(referrer_base="FULL_WIN")
    _run(referral.credit_referral_on_win(Player(), FIVE_TICKET_WIN, cfg, game_key=GAME, tickets=5))
    assert paid == [Decimal("250.00")]


def test_an_unknown_setting_means_one_ticket(paid):
    # `update_game` saves without validation, so a stray value must be safe.
    cfg = _cfg(referrer_base="whatever")
    _run(referral.credit_referral_on_win(Player(), FIVE_TICKET_WIN, cfg, game_key=GAME, tickets=5))
    assert paid == [Decimal("50.00")]


def test_still_only_the_first_win_per_game(paid):
    b = Player()
    _run(referral.credit_referral_on_win(b, FIVE_TICKET_WIN, _cfg(), game_key=GAME, tickets=5))
    _run(referral.credit_referral_on_win(b, FIVE_TICKET_WIN, _cfg(), game_key=GAME, tickets=5))
    _run(referral.credit_referral_on_win(b, FIVE_TICKET_WIN, _cfg(), game_key="btcUpDown", tickets=5))
    assert paid == [Decimal("50.00"), Decimal("50.00")]  # Nifty once, BTC once


def test_bracket_five_tickets_pay_the_same_as_one(paid):
    # Live Bracket economics: ticket 1100, multiplier 1.818189.
    cfg = GameConfig(ticket_price=1100.0, win_multiplier=1.818189, referrer_profit_pct=5.0)
    win = referral.credit_referral_on_win
    _run(win(Player(), Decimal("10000.04"), cfg, game_key="niftyBracket", tickets=5))
    _run(win(Player(), Decimal("2000.01"), cfg, game_key="niftyBracket", tickets=1))
    assert paid == [Decimal("100.00"), Decimal("100.00")]


def test_games_without_tickets_pay_on_the_full_winning(paid):
    # Jackpot callers pass no ticket count.
    _run(referral.credit_referral_on_win(Player(), Decimal("8000.00"), _cfg(), game_key="niftyJackpot"))
    assert paid == [Decimal("400.00")]


def test_a_reversal_claws_back_what_was_paid(paid):
    b = Player()
    _run(referral.credit_referral_on_win(b, FIVE_TICKET_WIN, _cfg(), game_key=GAME, tickets=5))
    report = _run(referral.reverse_referral_on_win(b, FIVE_TICKET_WIN, _cfg(), game_key=GAME, tickets=5))
    assert paid == [Decimal("50.00"), Decimal("-50.00")]
    assert report["reward"] == "50.00"
    assert b.game_referral.first_win_by_game[GAME] is False  # re-declare can pay again


def _bet(amount: str, tickets: int | None):
    return SimpleNamespace(amount=to_decimal128(Decimal(amount)), tickets=tickets)


def test_stake_tickets_stored_or_derived():
    # Up/Down and Bracket bets carry `amount` + `tickets`.
    cfg = _cfg()
    assert referral.stake_tickets(_bet("3000", 5), cfg) == 5
    # Placed before `tickets` existed: stake ÷ ticket price.
    assert referral.stake_tickets(_bet("3000", None), cfg) == 5
    assert referral.stake_tickets(_bet("3000", None), _cfg().model_copy(update={"ticket_price": 0})) == 1
    bracket = GameConfig(ticket_price=1100.0)
    assert referral.stake_tickets(_bet("5500", None), bracket) == 5
