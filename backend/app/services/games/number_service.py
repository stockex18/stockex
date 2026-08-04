"""Nifty + BTC Number — bet placement and daily result settlement.

Result = two digits of the closing price at `result_time`:
  • Nifty: the fractional (decimal) two digits — 23,123.65 → 65.
  • BTC:   the integer part's last two digits — 75,242.89 → 42.
Win when selected_number == result_number. Model B gross (full to user in v1).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from beanie import PydanticObjectId

from app.core.exceptions import (
    GameDisabledError,
    GameLimitExceededError,
    GameWindowClosedError,
)
from app.core.redis_client import publish
from app.models.games.bets import (
    GameBetStatus,
    GameManualResult,
    GameResult,
    NumberBet,
)
from app.models.games.settings import GameSettings
from app.services.games import price_resolver, wallet_service
from app.services.games.common import ist_datetime_for_day, ist_day, parse_hms
from app.services.games.payout_math import compute_number_payout
from app.utils.decimal_utils import quantize_money, to_decimal, to_decimal128
from app.utils.time_utils import now_ist, now_utc

logger = logging.getLogger(__name__)
_RESULT_GRACE_SEC = 20


async def _distribute_win(user_id, win_amount, game_key: str, cfg) -> None:
    """4-level %-of-WINNING split (hierarchy HELD + referrer games wallet),
    funded from the house. Base = gross winning amount (the full payout)."""
    try:
        from app.models.user import User
        from app.services.games import hierarchy, referral

        user = await User.get(user_id)
        if user is None:
            return
        if to_decimal(win_amount) <= 0:
            return
        await hierarchy.distribute_profit_split(user, win_amount, game_key, cfg)
        await referral.credit_referral_on_win(user, win_amount, cfg, game_key=game_key)
    except Exception:  # noqa: BLE001
        logger.exception("number_distribute_win_failed user=%s game=%s", user_id, game_key)


async def place_bet(
    user_id: PydanticObjectId, *, game_key: str, selected_number: int, quantity: int
) -> NumberBet:
    settings = await GameSettings.load_singleton()
    if not settings.games_enabled or settings.maintenance_mode:
        raise GameDisabledError("Games are currently unavailable")
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        raise GameDisabledError()

    hi = 99 if cfg.all_decimals else 95
    if selected_number < 0 or selected_number > hi:
        raise GameLimitExceededError(f"Number must be between 0 and {hi}")
    if not cfg.all_decimals and selected_number % 5 != 0:
        raise GameLimitExceededError("Number must be a multiple of 5")
    if quantity < 1 or quantity > cfg.max_tickets_per_number:
        raise GameLimitExceededError(
            f"Max {cfg.max_tickets_per_number} tickets per number"
        )

    now = now_ist()
    start_t = parse_hms(cfg.bidding_start_time)
    end_t = parse_hms(cfg.bidding_end_time)
    if not (start_t <= now.time() <= end_t):
        raise GameWindowClosedError("Bidding is closed for this game")

    day = now.strftime("%Y-%m-%d")
    # Daily bet-count + per-number caps.
    todays = await NumberBet.find(
        NumberBet.user_id == user_id, NumberBet.game_key == game_key, NumberBet.bet_date == day
    ).to_list()
    if len(todays) >= cfg.bets_per_day:
        raise GameLimitExceededError(f"Daily limit of {cfg.bets_per_day} bets reached")
    same_number_qty = sum(b.quantity for b in todays if b.selected_number == selected_number)
    if same_number_qty + quantity > cfg.max_tickets_per_number:
        raise GameLimitExceededError(
            f"Max {cfg.max_tickets_per_number} tickets on number {selected_number}"
        )

    tp = to_decimal(cfg.ticket_price)
    amt = quantize_money(tp * to_decimal(quantity))

    await wallet_service.atomic_games_wallet_debit(
        user_id, amt, game_key=game_key,
        description=f"Bet · {game_key} · #{selected_number} × {quantity}",
        meta={"kind": "BET", "number": selected_number, "qty": quantity},
    )
    await wallet_service.house_settle(amt, game_key=game_key, narration=f"Games stake in · {game_key} number")

    bet = NumberBet(
        user_id=user_id, game_key=game_key, selected_number=selected_number,
        quantity=quantity, amount=to_decimal128(amt), ticket_price=to_decimal128(tp),
        bet_date=day, status=GameBetStatus.PENDING,
    )
    await bet.insert()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_placed", "payload": {"game": game_key}})
    except Exception:
        pass
    return bet


async def _load_editable_bet(user_id, bet_id: str):
    """A PENDING number bet owned by the user whose bidding window is still open."""
    from app.models.games.settings import GameSettings

    try:
        bet = await NumberBet.get(PydanticObjectId(str(bet_id)))
    except Exception:
        bet = None
    if bet is None or bet.user_id != user_id:
        raise GameLimitExceededError("Bet not found")
    if bet.status != GameBetStatus.PENDING:
        raise GameWindowClosedError("This bet is already settled — can't change it")
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(bet.game_key)
    if cfg is None:
        raise GameDisabledError()
    now = now_ist()
    if not (parse_hms(cfg.bidding_start_time) <= now.time() <= parse_hms(cfg.bidding_end_time)):
        raise GameWindowClosedError("Bidding is closed — can't change the bet")
    return bet, cfg


async def modify_bet(user_id, bet_id: str, *, selected_number=None, quantity=None) -> NumberBet:
    """Change a live number bet's picked number and/or ticket quantity."""
    bet, cfg = await _load_editable_bet(user_id, bet_id)

    if quantity is not None:
        q = int(quantity)
        if q < 1 or q > cfg.max_tickets_per_number:
            raise GameLimitExceededError(f"Max {cfg.max_tickets_per_number} tickets per number")
        tp = to_decimal(cfg.ticket_price)
        new_amt = quantize_money(tp * to_decimal(q))
        diff = new_amt - to_decimal(bet.amount)
        if diff > 0:
            await wallet_service.atomic_games_wallet_debit(
                user_id, diff, game_key=bet.game_key,
                description=f"Modify bet · {bet.game_key} · +stake",
                meta={"kind": "BET_MODIFY", "bet_id": str(bet.id)},
            )
            await wallet_service.house_settle(diff, game_key=bet.game_key, narration="Bet modify · stake up")
        elif diff < 0:
            await wallet_service.atomic_games_wallet_credit(
                user_id, -diff, game_key=bet.game_key,
                description=f"Modify bet · {bet.game_key} · −stake refund",
                meta={"kind": "BET_MODIFY_REFUND", "bet_id": str(bet.id)},
            )
            await wallet_service.house_settle(diff, game_key=bet.game_key, narration="Bet modify · stake down")
        bet.quantity = q
        bet.amount = to_decimal128(new_amt)

    if selected_number is not None:
        n = int(selected_number)
        hi = 99 if cfg.all_decimals else 95
        if n < 0 or n > hi:
            raise GameLimitExceededError(f"Number must be between 0 and {hi}")
        if not cfg.all_decimals and n % 5 != 0:
            raise GameLimitExceededError("Number must be a multiple of 5")
        bet.selected_number = n

    bet.updated_at = now_utc()
    await bet.save()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_modified", "payload": {"game": bet.game_key}})
    except Exception:
        pass
    return bet


async def cancel_bet(user_id, bet_id: str) -> dict:
    """Cancel a live number bet and refund the full stake."""
    bet, _ = await _load_editable_bet(user_id, bet_id)
    refund = to_decimal(bet.amount)
    if refund > 0:
        await wallet_service.atomic_games_wallet_credit(
            user_id, refund, game_key=bet.game_key,
            description=f"Cancel bet · {bet.game_key} · refund",
            meta={"kind": "BET_CANCEL", "bet_id": str(bet.id)},
        )
        await wallet_service.house_settle(-refund, game_key=bet.game_key, narration="Bet cancelled · refund")
    bet.status = GameBetStatus.CANCELLED
    bet.updated_at = now_utc()
    await bet.save()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_cancelled", "payload": {"game": bet.game_key}})
    except Exception:
        pass
    return {"id": str(bet.id), "refunded": str(refund)}


def number_from_close(game_key: str, close) -> int:
    """Winning two-digit number for a number game, given a closing price.
    BTC → last two integer digits; NIFTY → the two fractional digits."""
    if game_key == "btcNumber":
        return price_resolver.btc_number_from_close(close)
    return price_resolver.nifty_number_from_close(close)


async def resolve_result(
    game_key: str, day: str, cfg, result_dt
) -> tuple[Decimal | None, int | None, str]:
    """Resolve (close_price, result_number, source) for a number game's day.

    Manual mode (`cfg.auto_result` False): read the super-admin's typed
    `GameManualResult`. If none typed yet, return (None, None, "manual_pending")
    so the settler WAITS — it must never silently fall back to the feed when
    the admin has chosen to set the result by hand.

    Auto mode (default): derive from the live broker close, exactly as before.
    """
    if not cfg.auto_result:
        mr = await GameManualResult.find_one(
            GameManualResult.game_key == game_key, GameManualResult.day == day
        )
        if mr is None:
            return None, None, "manual_pending"
        close = to_decimal(mr.close_price) if mr.close_price is not None else None
        return close, int(mr.result_number), "manual"

    if game_key == "btcNumber":
        close = await price_resolver.resolve_btc_price_at(result_dt)
    else:
        # STRICT: the winning digit must match the OFFICIAL close exactly, so
        # never settle on a last-traded candle or a stale cached value — wait
        # for the real official close (or use the manual-result override).
        close = await price_resolver.resolve_nifty_price_at(result_dt, strict=True, game_key=game_key)
    number = number_from_close(game_key, close) if close else None
    return close, number, "result_time"


async def _historical_close_for_day(game_key: str, result_dt) -> Decimal | None:
    """PURE historical close for a PAST day's result time — used only by the
    backfill. Unlike `resolve_result`'s auto path it never touches the live
    quote (which carries only TODAY's value), so it's safe for old days.

    BTC → the 1-minute Binance candle closing at result_dt (Binance keeps full
    history). NIFTY → the last Zerodha minute candle of that session; returns
    None on a holiday / weekend (no candles) so those days are simply skipped.
    """
    try:
        if game_key == "btcNumber":
            return await price_resolver.resolve_btc_price_at(result_dt)
        from app.services.zerodha_service import zerodha

        candles = await zerodha.get_historical(
            price_resolver.NIFTY_TOKEN,
            result_dt - timedelta(hours=6),
            result_dt + timedelta(minutes=1),
            "minute",
        )
        if candles:
            cl = to_decimal(candles[-1]["close"])
            if cl > 0:
                return quantize_money(cl)
    except Exception:
        logger.debug("historical_close_for_day_failed game=%s", game_key, exc_info=True)
    return None


async def backfill_recent_results(game_key: str, days: int = 7) -> int:
    """Self-heal the daily-results history. For each of the last `days` days
    whose result time has passed and that has NO published GameResult, resolve
    the historical close and insert one — so a day nobody bet on still shows in
    the user's "Last N days results" strip.

    BTC trades every calendar day, so every gap is filled. NIFTY only settles
    on trading days; a holiday/weekend returns no historical candle and is left
    out (correct — there was no session). Manual-mode games are still
    backfilled from the feed here: a MISSING past day never had a hand-typed
    value, and a real number beats a hole in the history.
    """
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(game_key)
    if cfg is None:
        return 0

    now = now_ist()
    result_t = parse_hms(cfg.result_time)
    filled = 0
    for back in range(days):
        d = ist_day(now - timedelta(days=back))
        result_dt = ist_datetime_for_day(d).replace(
            hour=result_t.hour, minute=result_t.minute, second=result_t.second
        )
        if now < result_dt + timedelta(seconds=_RESULT_GRACE_SEC):
            continue  # that day's result time hasn't arrived yet
        exists = await GameResult.find_one(
            GameResult.game_key == game_key, GameResult.day == d,
            GameResult.window_number == None,  # noqa: E711
        )
        if exists is not None:
            continue
        close = await _historical_close_for_day(game_key, result_dt)
        if close is None or close <= 0:
            continue
        number = number_from_close(game_key, close)
        try:
            await GameResult(
                game_key=game_key, day=d, window_number=None,
                close_price=to_decimal128(close), result=str(number),
                result_number=number, price_source="backfill",
            ).insert()
            filled += 1
        except Exception:
            pass  # raced with the live declare — fine
    if filled:
        logger.info("backfill_recent_results game=%s filled=%s", game_key, filled)
    return filled


async def declare_and_settle(game_key: str) -> int:
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        return 0

    pending = await NumberBet.find(
        NumberBet.game_key == game_key, NumberBet.status == GameBetStatus.PENDING
    ).to_list()

    now = now_ist()
    # For Nifty the resolver itself waits (via a stability gate) until NSE's
    # official clearing close stops moving, so we don't need an extra fixed delay
    # here — just the base result-time grace.
    grace_sec = _RESULT_GRACE_SEC
    result_t = parse_hms(cfg.result_time)
    by_day: dict[str, list[NumberBet]] = {}
    for b in pending:
        by_day.setdefault(b.bet_date, []).append(b)

    # Always DECLARE today's result at result_time, even with zero pending
    # bets — the user side ("show at 3:45") reads the published GameResult, so
    # it must exist whether or not anyone played. `bets` is then an empty list
    # and the settle loop below is a no-op for it.
    today = ist_day(now)
    if today not in by_day:
        result_dt_today = ist_datetime_for_day(today).replace(
            hour=result_t.hour, minute=result_t.minute, second=result_t.second
        )
        if now >= result_dt_today + timedelta(seconds=grace_sec):
            by_day[today] = []

    if not by_day:
        return 0

    settled = 0
    for day, bets in by_day.items():
        result_dt = ist_datetime_for_day(day).replace(
            hour=result_t.hour, minute=result_t.minute, second=result_t.second
        )
        if now < result_dt + timedelta(seconds=grace_sec):
            continue

        close, result_number, source = await resolve_result(game_key, day, cfg, result_dt)
        if result_number is None:
            # Manual mode waiting for the admin, or the feed is briefly
            # unavailable — retry next tick. Nothing is settled or published.
            # (In manual mode a typed NUMBER is enough; `close` is only for
            # display, so we key the wait on result_number, not close.)
            continue

        # Declared-guard row (unique on game_key/day/window=None). In manual
        # mode the admin may type only the number — store 0 close then.
        existing = await GameResult.find_one(
            GameResult.game_key == game_key, GameResult.day == day,
            GameResult.window_number == None,  # noqa: E711
        )
        if existing is None:
            try:
                await GameResult(
                    game_key=game_key, day=day, window_number=None,
                    close_price=to_decimal128(close) if close is not None else to_decimal128(Decimal("0")),
                    result=str(result_number),
                    result_number=result_number, price_source=source,
                ).insert()
            except Exception:
                pass

        for bet in bets:
            won = bet.selected_number == result_number
            if won:
                payout = compute_number_payout(
                    fixed_profit=cfg.fixed_profit, ticket_price=cfg.ticket_price,
                    win_multiplier=cfg.win_multiplier, quantity=bet.quantity,
                )
                await wallet_service.atomic_games_wallet_credit(
                    bet.user_id, payout, game_key=game_key,
                    description=f"Win · {game_key} · #{result_number}",
                    meta={"kind": "WIN", "number": result_number}, is_win=True,
                )
                await wallet_service.house_settle(-payout, game_key=game_key, narration=f"Games payout · {game_key} number")
                bet.status = GameBetStatus.WON
                bet.payout = to_decimal128(payout)
                # 4-level %-of-WINNING split — base = gross winning (full payout).
                await _distribute_win(bet.user_id, to_decimal(payout), game_key, cfg)
            else:
                bet.status = GameBetStatus.LOST
                bet.payout = to_decimal128(Decimal("0"))
            bet.result_number = result_number
            bet.updated_at = now_utc()
            await bet.save()
            settled += 1
            try:
                await publish(
                    f"user:{bet.user_id}:games",
                    {"type": "bet_result", "payload": {
                        "game": game_key, "result": result_number, "won": won,
                        "payout": str(bet.payout)}},
                )
            except Exception:
                pass
    return settled
