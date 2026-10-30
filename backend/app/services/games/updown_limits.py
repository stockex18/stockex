"""Up/Down per-window ticket cap.

One user may hold at most `GameConfig.max_tickets_per_window` tickets in one
window of one game -- UP and DOWN together, across every bet they place and
every stake change they make in that window (0 = no cap).

The record of what a user holds is their `UpDownBet` rows for that window, so
nothing can drift out of step with the bets themselves. What makes the check
safe is a short Redis lock per (game, day, window, user): two taps, two tabs
or two API instances can't both read "3 used" and both add 3. The lock is held
only across check → debit → insert, so the user never waits on anyone else.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from beanie import PydanticObjectId

from app.core.exceptions import GameLimitExceededError
from app.core.redis_client import get_redis
from app.models.games.bets import UpDownBet
from app.utils.decimal_utils import to_decimal

_LOCK_TTL_MS = 10_000  # a stuck holder frees itself; a bet takes well under 1 s
_LOCK_WAIT_TRIES = 30  # × 0.1 s
_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


def ticket_count(amount, ticket_price) -> int:
    """Tickets in a stake: amount ÷ ticket price, the same rounding as
    `place_bet` uses to validate it."""
    tp = to_decimal(ticket_price)
    if tp <= 0:
        return 0
    return int((to_decimal(amount) / tp).to_integral_value())


@asynccontextmanager
async def window_lock(user_id, game_key: str, day: str, window: int) -> AsyncIterator[None]:
    """Serialise one user's bets for one window."""
    r = get_redis()
    key = f"games:updown:wcap:{game_key}:{day}:{window}:{user_id}"
    token = secrets.token_hex(8)
    for _ in range(_LOCK_WAIT_TRIES):
        if await r.set(key, token, nx=True, px=_LOCK_TTL_MS):
            break
        await asyncio.sleep(0.1)
    else:
        raise GameLimitExceededError("Your previous bet is still going through. Please try again.")
    try:
        yield
    finally:
        # Only our own lock; if Redis hiccups here the TTL frees it anyway.
        with suppress(Exception):
            await r.eval(_RELEASE, 1, key, token)


async def tickets_in_window(
    user_id: PydanticObjectId, game_key: str, day: str, window: int, ticket_price,
    *, exclude_bet_id: PydanticObjectId | None = None,
) -> int:
    """Tickets the user already holds in this window, UP and DOWN together.
    `exclude_bet_id` leaves out a bet that is being modified."""
    bets = await UpDownBet.find(
        {"user_id": user_id, "game_key": game_key, "settlement_day": day, "window_number": window}
    ).to_list()
    return sum(ticket_count(b.amount, ticket_price) for b in bets if b.id != exclude_bet_id)


def check_window_cap(cap: int, used: int, adding: int, *, modifying: bool = False) -> None:
    """Raise if `adding` more tickets would take the user past the cap.

    `modifying`: `adding` is an existing bet's new size and `used` is the
    user's OTHER bets in the window, so the message says what this bet can be."""
    cap = int(cap or 0)
    if cap <= 0 or used + adding <= cap:
        return
    left = max(0, cap - used)
    if modifying:
        raise GameLimitExceededError(
            f"You can buy up to {cap} tickets per window, so this bet can have at most "
            f"{left} ticket{'' if left == 1 else 's'}."
        )
    if left == 0:
        raise GameLimitExceededError(
            f"You can buy up to {cap} tickets per window, and you have used all {cap}. "
            "Try again in the next window."
        )
    raise GameLimitExceededError(
        f"You can buy up to {cap} tickets per window. You have {left} left in this window."
    )
