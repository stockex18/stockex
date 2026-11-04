"""Up/Down per-window ticket cap.

What has to hold:

  * a user holds at most `max_tickets_per_window` (5) tickets in one window
    ON EACH SIDE -- up to 5 UP and, separately, up to 5 DOWN: 5 UP in one bet
    fits, a 6th UP is refused, but DOWN still has its own 5; 3 + 2 on one side
    fits, 3 + 3 is refused with how many are left on that side;
  * changing a bet's direction counts it against the side it moves to;
  * a refused bet takes no money;
  * Nifty and BTC are separate, and the next window starts fresh;
  * changing a bet's stake replaces its tickets rather than adding to them;
  * two bets at the same moment can't both squeeze into the same tickets
    left (the per-window lock);
  * 0 means no cap.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from beanie import PydanticObjectId

from app.core.exceptions import GameLimitExceededError
from app.models.games.bets import UpDownPrediction
from app.models.games.settings import GameConfig
from app.services.games import updown_limits, updown_service
from app.utils.decimal_utils import to_decimal128

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 30, 10, 5, tzinfo=IST)  # inside a Nifty betting window
DAY = "2026-10-30"
PRICE = Decimal("600")


def _run(c):
    return asyncio.run(c)


class FakeRedis:
    """Just enough Redis for the per-window lock: SET NX PX + compare-delete."""

    def __init__(self):
        self.d: dict = {}

    async def set(self, k, v, nx=False, px=None):
        if nx and k in self.d:
            return None
        self.d[k] = v
        return True

    async def eval(self, script, numkeys, key, token):
        if self.d.get(key) == token:
            del self.d[key]
            return 1
        return 0


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(updown_limits, "get_redis", lambda: r)
    return r


# ── the rule ─────────────────────────────────────────────────────────────


def test_ticket_count_matches_place_bet_rounding():
    assert updown_limits.ticket_count(Decimal("3000"), PRICE) == 5
    assert updown_limits.ticket_count(Decimal("600"), PRICE) == 1
    assert updown_limits.ticket_count(Decimal("600"), Decimal("0")) == 0


@pytest.mark.parametrize(("used", "adding"), [(0, 5), (3, 2), (4, 1)])
def test_up_to_the_cap_fits(used, adding):
    updown_limits.check_window_cap(5, used, adding, prediction="UP")


def test_over_the_cap_says_how_many_are_left_on_that_side():
    with pytest.raises(GameLimitExceededError, match="2 DOWN left in this window"):
        updown_limits.check_window_cap(5, 3, 3, prediction="DOWN")


def test_a_full_side_says_so():
    with pytest.raises(GameLimitExceededError, match="up to 5 UP tickets.*used all 5"):
        updown_limits.check_window_cap(5, 5, 1, prediction=UpDownPrediction.UP)


def test_a_stake_change_says_what_this_bet_can_be():
    # Other UP bets hold 2; raising this one to 4 would make 6.
    with pytest.raises(GameLimitExceededError, match="at most 3 tickets on UP"):
        updown_limits.check_window_cap(5, 2, 4, prediction="UP", modifying=True)
    updown_limits.check_window_cap(5, 2, 3, prediction="UP", modifying=True)


def test_zero_means_no_cap():
    updown_limits.check_window_cap(0, 400, 100, prediction="UP")


def test_the_default_cap_is_five():
    assert GameConfig().max_tickets_per_window == 5


# ── counting what a user holds ───────────────────────────────────────────


def test_up_and_down_are_counted_separately_and_a_modified_bet_is_left_out(monkeypatch):
    me = PydanticObjectId()
    up = SimpleNamespace(id=PydanticObjectId(), amount=to_decimal128(Decimal("1800")),
                         prediction=UpDownPrediction.UP)    # 3 UP
    up2 = SimpleNamespace(id=PydanticObjectId(), amount=to_decimal128(Decimal("600")),
                          prediction=UpDownPrediction.UP)   # 1 UP
    down = SimpleNamespace(id=PydanticObjectId(), amount=to_decimal128(Decimal("1200")),
                           prediction=UpDownPrediction.DOWN)  # 2 DOWN

    class Q:
        async def to_list(self):
            return [up, up2, down]

    monkeypatch.setattr(updown_limits.UpDownBet, "find", classmethod(lambda cls, *a, **k: Q()))
    count = updown_limits.tickets_in_window
    assert _run(count(me, "niftyUpDown", DAY, 4, PRICE, prediction="UP")) == 4
    assert _run(count(me, "niftyUpDown", DAY, 4, PRICE, prediction="DOWN")) == 2
    assert _run(count(me, "niftyUpDown", DAY, 4, PRICE, prediction="UP", exclude_bet_id=up.id)) == 1


def test_the_stored_ticket_count_is_used_when_there_is_one(monkeypatch):
    # Placed as 5 tickets at 600; the price has since changed to 1000.
    bet = SimpleNamespace(id=PydanticObjectId(), amount=to_decimal128(Decimal("3000")), tickets=5,
                          prediction=UpDownPrediction.UP)

    class Q:
        async def to_list(self):
            return [bet]

    monkeypatch.setattr(updown_limits.UpDownBet, "find", classmethod(lambda cls, *a, **k: Q()))
    held = updown_limits.tickets_in_window(
        PydanticObjectId(), "niftyUpDown", DAY, 4, Decimal("1000"), prediction="UP"
    )
    assert _run(held) == 5


def test_a_stake_change_updates_the_stored_ticket_count(monkeypatch):
    """The referrer's one-ticket share divides the payout by `tickets`, so a
    2-ticket bet raised to 5 must say 5, not 2."""

    async def noop(*_, **__):
        return None

    async def none_held(*_, **__):
        return 0

    monkeypatch.setattr(updown_service.wallet_service, "atomic_games_wallet_debit", noop)
    monkeypatch.setattr(updown_service.wallet_service, "atomic_games_wallet_credit", noop)
    monkeypatch.setattr(updown_service.wallet_service, "house_settle", noop)
    monkeypatch.setattr(updown_service, "publish", noop)
    monkeypatch.setattr(updown_limits, "tickets_in_window", none_held)

    bet = SimpleNamespace(
        id=PydanticObjectId(), game_key="niftyUpDown", settlement_day=DAY, window_number=4,
        amount=to_decimal128(Decimal("1200")), tickets=2, prediction=UpDownPrediction.UP, save=noop,
    )
    cfg = GameConfig(ticket_price=600.0, max_tickets_per_window=5)
    _run(updown_service._apply_modify(PydanticObjectId(), bet, cfg, prediction=None, amount=3000))
    assert bet.tickets == 5


# ── the lock ─────────────────────────────────────────────────────────────


def test_two_bets_at_once_cannot_both_fit(redis):
    """3 + 3 arriving together with 0 used: exactly one gets in."""
    held: list[int] = []
    outcome: list[str] = []

    async def bet(n):
        try:
            async with updown_limits.window_lock("u1", "niftyUpDown", DAY, 4):
                used = sum(held)
                updown_limits.check_window_cap(5, used, n, prediction="UP")
                await asyncio.sleep(0.02)  # the debit + insert
                held.append(n)
            outcome.append("ok")
        except GameLimitExceededError:
            outcome.append("refused")

    async def both():
        await asyncio.gather(bet(3), bet(3))

    _run(both())
    assert sorted(outcome) == ["ok", "refused"]
    assert sum(held) == 3
    assert redis.d == {}  # lock released


def test_a_stuck_lock_gives_a_friendly_error(redis, monkeypatch):
    monkeypatch.setattr(updown_limits, "_LOCK_WAIT_TRIES", 2)
    redis.d["games:updown:wcap:niftyUpDown:2026-10-30:4:u1"] = "someone-else"

    async def go():
        async with updown_limits.window_lock("u1", "niftyUpDown", DAY, 4):
            pass

    with pytest.raises(GameLimitExceededError, match="still going through"):
        _run(go())


def test_the_lock_is_per_window_and_per_game(redis):
    async def go():
        async with updown_limits.window_lock("u1", "niftyUpDown", DAY, 4):
            # Same user, other game / next window: not blocked.
            async with updown_limits.window_lock("u1", "btcUpDown", DAY, 4):
                pass
            async with updown_limits.window_lock("u1", "niftyUpDown", DAY, 5):
                pass

    _run(go())


# ── place_bet end to end (wallet, clock and DB faked) ────────────────────


@pytest.fixture
def game(monkeypatch, redis):
    """A live Nifty Up/Down window with a fake bet store and wallet."""
    cfg = GameConfig(
        ticket_price=600.0, min_tickets=1, max_tickets=500, max_tickets_per_window=5,
        start_time="09:15:00", end_time="15:00:00", round_duration=900, win_multiplier=1.66667,
    )
    settings = SimpleNamespace(
        games_enabled=True, maintenance_mode=False,
        games={"niftyUpDown": cfg, "btcUpDown": cfg.model_copy()},
    )
    store: list = []
    debited: list[Decimal] = []

    async def load():
        return settings

    async def noop(*_, **__):
        return None

    async def debit(user_id, amount, **_):
        debited.append(Decimal(str(amount)))

    async def held(user_id, game_key, day, window, ticket_price, *, prediction, exclude_bet_id=None):
        side = updown_limits.side_of(prediction)
        return sum(
            updown_limits.ticket_count(b.amount, ticket_price) for b in store
            if b.user_id == user_id and b.game_key == game_key
            and b.settlement_day == day and b.window_number == window and b.id != exclude_bet_id
            and updown_limits.side_of(b.prediction) == side
        )

    class FakeBet(SimpleNamespace):
        def __init__(self, **kw):
            super().__init__(id=PydanticObjectId(), **kw)

        async def insert(self):
            store.append(self)

    monkeypatch.setattr(updown_service, "GameSettings", SimpleNamespace(load_singleton=load))
    monkeypatch.setattr(updown_service, "now_ist", lambda: NOW)
    monkeypatch.setattr(updown_service, "assert_nse_open_today", noop)
    monkeypatch.setattr(updown_service, "publish", noop)
    monkeypatch.setattr(updown_service, "UpDownBet", FakeBet)
    monkeypatch.setattr(updown_service.wallet_service, "atomic_games_wallet_debit", debit)
    monkeypatch.setattr(updown_service.wallet_service, "house_settle", noop)
    monkeypatch.setattr(updown_limits, "tickets_in_window", held)
    return SimpleNamespace(store=store, debited=debited, cfg=cfg)


def _place(user, tickets, prediction="UP", game_key="niftyUpDown"):
    return _run(updown_service.place_bet(
        user, game_key=game_key, prediction=prediction,
        amount=tickets * 600, entry_price=24000, window_number=0,
    ))


def test_place_bet_five_up_fit_the_sixth_up_is_refused_and_costs_nothing(game):
    me = PydanticObjectId()
    _place(me, 3, "UP")
    _place(me, 2, "UP")  # 5 UP
    with pytest.raises(GameLimitExceededError, match="5 UP tickets.*used all 5"):
        _place(me, 1, "UP")
    assert game.debited == [Decimal("1800"), Decimal("1200")]  # nothing for the refused one


def test_place_bet_down_has_its_own_five_alongside_a_full_up(game):
    me = PydanticObjectId()
    _place(me, 5, "UP")
    _place(me, 3, "DOWN")
    _place(me, 2, "DOWN")  # 5 UP + 5 DOWN
    with pytest.raises(GameLimitExceededError, match="5 DOWN tickets.*used all 5"):
        _place(me, 1, "DOWN")
    with pytest.raises(GameLimitExceededError, match="UP"):
        _place(me, 1, "UP")
    assert len(game.store) == 3


def test_place_bet_other_users_and_btc_have_their_own_five(game):
    a, b = PydanticObjectId(), PydanticObjectId()
    _place(a, 5)
    _place(b, 5)
    _place(a, 5, game_key="btcUpDown")
    assert len(game.store) == 3


def test_place_bet_cap_zero_is_unlimited(game):
    game.cfg.max_tickets_per_window = 0
    _place(PydanticObjectId(), 50)


# ── modify: a direction change counts against the side it moves to ──────


def _modify(bet, cfg, *, prediction=None, amount=None):
    return _run(updown_service._apply_modify(bet.user_id, bet, cfg, prediction=prediction, amount=amount))


@pytest.fixture
def modify_game(game, monkeypatch):
    async def noop(*_, **__):
        return None

    monkeypatch.setattr(updown_service.wallet_service, "atomic_games_wallet_credit", noop)
    for b in game.store:
        b.save = noop
    return game


def _bet_in_store(game, user, tickets, prediction):
    _place(user, tickets, prediction)
    b = game.store[-1]

    async def noop(*_, **__):
        return None

    b.save = noop
    b.tickets = tickets
    return b


def test_switching_a_bet_to_a_full_side_is_refused(modify_game):
    me = PydanticObjectId()
    _bet_in_store(modify_game, me, 5, "UP")
    down = _bet_in_store(modify_game, me, 2, "DOWN")
    with pytest.raises(GameLimitExceededError, match="on UP"):
        _modify(down, modify_game.cfg, prediction="UP")
    assert updown_limits.side_of(down.prediction) == "DOWN"  # unchanged


def test_switching_a_bet_to_a_side_with_room_is_allowed(modify_game):
    me = PydanticObjectId()
    _bet_in_store(modify_game, me, 3, "UP")
    down = _bet_in_store(modify_game, me, 2, "DOWN")
    _modify(down, modify_game.cfg, prediction="UP")  # 3 + 2 = 5 UP
    assert updown_limits.side_of(down.prediction) == "UP"


def test_switching_side_and_stake_together_is_checked_on_the_new_side(modify_game):
    me = PydanticObjectId()
    _bet_in_store(modify_game, me, 3, "UP")
    down = _bet_in_store(modify_game, me, 1, "DOWN")
    with pytest.raises(GameLimitExceededError, match="at most 2 tickets on UP"):
        _modify(down, modify_game.cfg, prediction="UP", amount=3 * 600)
    _modify(down, modify_game.cfg, prediction="UP", amount=2 * 600)
    assert down.tickets == 2
