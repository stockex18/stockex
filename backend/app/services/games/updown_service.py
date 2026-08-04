"""Nifty + BTC Up/Down — bet placement and window settlement.

Both games share this module (parameterised by `game_key` + price resolver).
Model A payout: winner receives full stake × win_multiplier from the house.
TIE (open == close) counts as a loss. Double-credit is impossible thanks to
the `UpDownWindowSettlement` unique index (insert-then-credit).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from app.core.exceptions import (
    GameDisabledError,
    GameLimitExceededError,
    GameWindowClosedError,
)
from app.core.redis_client import publish
from app.models.games.bets import (
    GameBetStatus,
    GameResult,
    UpDownBet,
    UpDownPrediction,
    UpDownWindowSettlement,
)
from app.models.games.settings import GameSettings
from app.services.games import price_resolver, wallet_service
from app.services.games.common import (
    ist_datetime_for_day,
    parse_hms,
    window_open_close_ist,
    window_number_for,
)
from app.services.games.payout_math import (
    compute_updown_win_payout,
    settle_updown_from_prices,
    updown_bet_won,
)
from app.utils.decimal_utils import quantize_money, to_decimal, to_decimal128
from app.utils.time_utils import now_ist, now_utc

logger = logging.getLogger(__name__)

# Seconds after a window's close before we resolve it (lets the authoritative
# candle finalise).
# Wait this long after a window closes before resolving its candle. The
# Zerodha 15m historical candle can still shift by a rupee or two in the first
# few seconds after close (late-arriving ticks / consolidation); 90 s lets it
# settle so the FIRST resolution is already the finalized value.
_RESOLVE_GRACE_SEC = 90


async def _resolve_window_pinned(resolver, game_key: str, day: str, window: int, open_dt, close_dt):
    """Resolve a window's (open, close, source), PINNED per (game, day, window).

    A window's close is needed twice — as the OUTCOME of window W-1 and as the
    REFERENCE of window W — and the two settlements happen ~15 min apart. If the
    Zerodha candle shifts by a rupee between those two fetches, W-1 and W would
    disagree on the shared boundary and a tiny move could settle in opposite
    directions. Pinning the first resolution (3-day TTL) makes both reads
    identical, so adjacent results are always consistent."""
    from app.core.redis_client import cache_get, cache_set

    key = f"games:updown:wclose:{game_key}:{day}:{window}"
    try:
        pinned = await cache_get(key)
        if isinstance(pinned, dict) and pinned.get("o") and pinned.get("c"):
            return to_decimal(pinned["o"]), to_decimal(pinned["c"]), pinned.get("s", "pinned")
    except Exception:
        pass
    res = await resolver(open_dt, close_dt)
    if res is None:
        return None
    o, c, src = res
    try:
        await cache_set(key, {"o": str(o), "c": str(c), "s": src}, ttl_sec=259200)  # 3 days
    except Exception:
        pass
    return o, c, src


def _resolver_for(game_key: str):
    return (
        price_resolver.resolve_btc_window
        if game_key == "btcUpDown"
        else price_resolver.resolve_nifty_window
    )


async def _distribute_win(user_id, stake, payout, game_key: str, cfg) -> None:
    """4-level %-of-WINNING split (hierarchy HELD + referrer games wallet),
    funded from the house. Base = gross winning amount (the full payout)."""
    try:
        from app.models.user import User
        from app.services.games import hierarchy, referral

        user = await User.get(user_id)
        if user is None:
            return
        win_amount = to_decimal(payout)  # gross winning (NOT payout − stake)
        if win_amount <= 0:
            return
        await hierarchy.distribute_profit_split(user, win_amount, game_key, cfg)
        await referral.credit_referral_on_win(user, win_amount, cfg, game_key=game_key)
    except Exception:  # noqa: BLE001 — never break settlement on commission
        logger.exception("updown_distribute_win_failed user=%s game=%s", user_id, game_key)


async def place_bet(
    user_id: PydanticObjectId,
    *,
    game_key: str,
    prediction: str,
    amount,
    entry_price,
    window_number: int,
) -> UpDownBet:
    settings = await GameSettings.load_singleton()
    if not settings.games_enabled or settings.maintenance_mode:
        raise GameDisabledError("Games are currently unavailable")
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        raise GameDisabledError()

    amt = quantize_money(to_decimal(amount))
    tp = to_decimal(cfg.ticket_price)
    if tp <= 0:
        raise GameLimitExceededError("Invalid ticket price")
    tickets = int((amt / tp).to_integral_value())
    if tickets < cfg.min_tickets or tickets > cfg.max_tickets:
        raise GameLimitExceededError(
            f"Tickets must be between {cfg.min_tickets} and {cfg.max_tickets}"
        )
    if amt <= 0:
        raise GameLimitExceededError("Amount must be positive")

    # Window must be currently open.
    now = now_ist()
    # Hard betting window per config — betting is only open in
    # [start_time, end_time) (spec: Nifty 09:15→15:00, BTC 00:00→22:30).
    tod = now.time()
    if (cfg.start_time and tod < parse_hms(cfg.start_time)) or (
        cfg.end_time and tod >= parse_hms(cfg.end_time)
    ):
        raise GameWindowClosedError()
    current = window_number_for(now, cfg.start_time, cfg.round_duration)
    if current <= 0:
        raise GameWindowClosedError()
    # Accept a bet only for the live window (client passes it; server is truth).
    day = now.strftime("%Y-%m-%d")
    open_dt, close_dt = window_open_close_ist(now, cfg.start_time, cfg.round_duration, current)
    if not (open_dt <= now < close_dt):
        raise GameWindowClosedError()

    pred = UpDownPrediction(prediction.upper())

    # Debit stake from games wallet (atomic, non-negative) then house collects.
    await wallet_service.atomic_games_wallet_debit(
        user_id, amt, game_key=game_key,
        description=f"Bet · {game_key} · Window #{current} · {pred.value}",
        meta={"kind": "BET", "window": current, "prediction": pred.value},
    )
    await wallet_service.house_settle(
        amt, game_key=game_key, narration=f"Games stake in · {game_key} W#{current}"
    )

    bet = UpDownBet(
        user_id=user_id, game_key=game_key, prediction=pred,
        amount=to_decimal128(amt), entry_price=to_decimal128(to_decimal(entry_price)),
        window_number=current, settlement_day=day, status=GameBetStatus.PENDING,
    )
    await bet.insert()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_placed", "payload": {"game": game_key, "window": current}})
    except Exception:
        pass
    return bet


async def _load_editable_bet(user_id: PydanticObjectId, bet_id: str) -> tuple[UpDownBet, object]:
    """Fetch a PENDING bet owned by the user whose window is STILL OPEN — the
    only state in which it may be modified or cancelled. Raises otherwise."""
    try:
        bet = await UpDownBet.get(PydanticObjectId(str(bet_id)))
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
    tod = now.time()
    if (cfg.start_time and tod < parse_hms(cfg.start_time)) or (
        cfg.end_time and tod >= parse_hms(cfg.end_time)
    ):
        raise GameWindowClosedError("Window closed — can't change the bet")
    current = window_number_for(now, cfg.start_time, cfg.round_duration)
    if current <= 0 or bet.window_number != current:
        raise GameWindowClosedError("Window closed — can't change the bet")
    open_dt, close_dt = window_open_close_ist(now, cfg.start_time, cfg.round_duration, current)
    if not (open_dt <= now < close_dt):
        raise GameWindowClosedError("Window closed — can't change the bet")
    return bet, cfg


async def modify_bet(
    user_id: PydanticObjectId, bet_id: str, *, prediction=None, amount=None
) -> UpDownBet:
    """Change a live Up/Down bet's direction and/or stake (same window only)."""
    bet, cfg = await _load_editable_bet(user_id, bet_id)

    if amount is not None:
        new_amt = quantize_money(to_decimal(amount))
        tp = to_decimal(cfg.ticket_price)
        if tp <= 0 or new_amt <= 0:
            raise GameLimitExceededError("Amount must be positive")
        tickets = int((new_amt / tp).to_integral_value())
        if tickets < cfg.min_tickets or tickets > cfg.max_tickets:
            raise GameLimitExceededError(
                f"Tickets must be between {cfg.min_tickets} and {cfg.max_tickets}"
            )
        diff = new_amt - to_decimal(bet.amount)
        if diff > 0:  # staking more → debit the difference
            await wallet_service.atomic_games_wallet_debit(
                user_id, diff, game_key=bet.game_key,
                description=f"Modify bet · {bet.game_key} · +stake",
                meta={"kind": "BET_MODIFY", "bet_id": str(bet.id)},
            )
            await wallet_service.house_settle(diff, game_key=bet.game_key, narration="Bet modify · stake up")
        elif diff < 0:  # staking less → refund the difference
            await wallet_service.atomic_games_wallet_credit(
                user_id, -diff, game_key=bet.game_key,
                description=f"Modify bet · {bet.game_key} · −stake refund",
                meta={"kind": "BET_MODIFY_REFUND", "bet_id": str(bet.id)},
            )
            await wallet_service.house_settle(diff, game_key=bet.game_key, narration="Bet modify · stake down")
        bet.amount = to_decimal128(new_amt)

    if prediction is not None:
        bet.prediction = UpDownPrediction(str(prediction).upper())

    bet.updated_at = now_utc()
    await bet.save()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_modified", "payload": {"game": bet.game_key}})
    except Exception:
        pass
    return bet


async def cancel_bet(user_id: PydanticObjectId, bet_id: str) -> dict:
    """Cancel a live Up/Down bet and refund the full stake."""
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


# ── Result model: NEXT-window outcome ──────────────────────────────────
# A bet placed in window W is a prediction about the NEXT 15-min window:
#   • reference price = the CLOSE of window W (locked when W ends)
#   • outcome price   = the CLOSE of window W+1
#   • UP wins if close(W+1) > close(W); DOWN if <; TIE (loss) if ==.
# This removes the "bet 1 min before close on the obvious direction" exploit —
# at bet time the move you're predicting (W→W+1) hasn't happened yet.
# The GameResult for window W stores open_price = close(W), close_price =
# close(W+1) so the "Last N results" strip reads the outcome directly.
async def _get_or_declare_result(game_key: str, cfg, resolver, day: str, window: int, now):
    """Return (result, outcome_price) for window `window`, declaring the
    GameResult if the NEXT window has closed. None when not settleable yet
    (next window still open, or price unavailable)."""
    existing = await GameResult.find_one(
        GameResult.game_key == game_key,
        GameResult.day == day,
        GameResult.window_number == window,
    )
    if existing is not None:
        return existing.result, to_decimal(existing.close_price)

    day_dt = ist_datetime_for_day(day)
    open_w, close_w = window_open_close_ist(day_dt, cfg.start_time, cfg.round_duration, window)
    open_n, close_n = window_open_close_ist(day_dt, cfg.start_time, cfg.round_duration, window + 1)
    # Only windows that were actually BETTABLE get a published result. A window
    # whose open is at/after end_time is past betting close (Nifty: the
    # 15:00→15:15 window opens exactly at end_time 15:00) — nobody can bet in it,
    # and its outcome is the post-close 15:30 clearing print (last-30-min VWAP),
    # not a fair live 15-min move. Drop it so the results strip stops at the last
    # bettable window (Nifty → last shown outcome is 15:15).
    if cfg.end_time and open_w.time() >= parse_hms(cfg.end_time):
        return None
    # Settle only AFTER the next window (W+1) has fully closed.
    if now < close_n + timedelta(seconds=_RESOLVE_GRACE_SEC):
        return None
    # Pinned per window so the shared boundary close(W+1) is IDENTICAL whether
    # read here (as W's outcome) or later when settling W+1 (as its reference).
    ref = await _resolve_window_pinned(resolver, game_key, day, window, open_w, close_w)
    fin = await _resolve_window_pinned(resolver, game_key, day, window + 1, open_n, close_n)
    if ref is None or fin is None:
        return None  # price unavailable — retry next tick
    ref_price = ref[1]      # close of window W (the reference)
    final_price = fin[1]    # close of window W+1 (the outcome)
    result = settle_updown_from_prices(ref_price, final_price)
    try:
        await GameResult(
            game_key=game_key, day=day, window_number=window,
            open_price=to_decimal128(ref_price), close_price=to_decimal128(final_price),
            result=result, price_source=fin[2],
        ).insert()
    except DuplicateKeyError:
        existing = await GameResult.find_one(
            GameResult.game_key == game_key,
            GameResult.day == day,
            GameResult.window_number == window,
        )
        if existing is not None:
            return existing.result, to_decimal(existing.close_price)
    return result, final_price


async def declare_recent_results(game_key: str, count: int = 8) -> int:
    """Declare a GameResult for the last `count` settleable windows even when
    NO ONE bet on them, so the "Last N results" strip shows a continuous
    UP/DOWN history. A window W is settleable once window W+1 has closed, so
    the most-recent settleable window is `current-2`. Idempotent."""
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        return 0

    now = now_ist()
    current = window_number_for(now, cfg.start_time, cfg.round_duration)
    if current <= 2:
        return 0
    day = now.strftime("%Y-%m-%d")
    resolver = _resolver_for(game_key)
    declared = 0
    # W is settleable only after W+1 closed → newest settleable is current-2.
    for window in range(current - 2, max(0, current - 2 - count), -1):
        r = await _get_or_declare_result(game_key, cfg, resolver, day, window, now)
        if r is not None:
            declared += 1
    return declared


async def declare_and_settle(game_key: str) -> int:
    """Resolve every closed window that still has PENDING bets and settle
    them. Returns the number of bets settled this pass."""
    # First make sure every recently-closed window has a published result,
    # so windows nobody bet on still appear in the results history.
    try:
        await declare_recent_results(game_key)
    except Exception:  # noqa: BLE001 — never block bet settlement on this
        logger.exception("declare_recent_results_failed game=%s", game_key)

    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        return 0

    pending = await UpDownBet.find(
        UpDownBet.game_key == game_key,
        UpDownBet.status == GameBetStatus.PENDING,
    ).to_list()
    if not pending:
        return 0

    # Group by (day, window).
    groups: dict[tuple[str, int], list[UpDownBet]] = {}
    for b in pending:
        groups.setdefault((b.settlement_day, b.window_number), []).append(b)

    now = now_ist()
    settled = 0
    resolver = _resolver_for(game_key)

    for (day, window), bets in groups.items():
        # Result comes from the NEXT window (W+1) closing vs window W's close.
        # `_get_or_declare_result` returns None until W+1 has closed, and
        # locks to the PUBLISHED GameResult so a later settlement pass (e.g. a
        # user's 2nd bet in the same window) reuses the SAME result — the
        # resolver's live-price fallback can't flip UP↔DOWN and pay both sides.
        r = await _get_or_declare_result(game_key, cfg, resolver, day, window, now)
        if r is None:
            continue  # next window not closed yet / price unavailable
        result, close_price = r

        mult = cfg.win_multiplier
        for bet in bets:
            won = updown_bet_won(bet.prediction.value, result)
            if won:
                new_status = GameBetStatus.WON
                payout = compute_updown_win_payout(to_decimal(bet.amount), mult)
            else:
                new_status = GameBetStatus.TIE if result == "TIE" else GameBetStatus.LOST
                payout = Decimal("0")

            # Per-BET atomic claim (PENDING → result). Replaces the old
            # per-(user, window) UpDownWindowSettlement guard, which wrongly
            # blocked a user's SECOND bet in the same window — e.g. hedging
            # UP *and* DOWN — leaving it stuck PENDING forever (only one
            # UpDownWindowSettlement row is allowed per user+window, so the
            # 2nd insert hit DuplicateKeyError → `continue`). Keying the guard
            # on the bet id lets every bet settle while still preventing a
            # concurrent tick / worker from double-crediting the same bet.
            claimed = await UpDownBet.get_motor_collection().find_one_and_update(
                {"_id": bet.id, "status": GameBetStatus.PENDING.value},
                {"$set": {
                    "status": new_status.value,
                    "payout": to_decimal128(payout),
                    "result_price": to_decimal128(close_price),
                    "updated_at": now_utc(),
                }},
            )
            if claimed is None:
                continue  # already settled by a concurrent tick / worker

            if won:
                await wallet_service.atomic_games_wallet_credit(
                    bet.user_id, payout, game_key=game_key,
                    description=f"Win · {game_key} · Window #{window} · {result}",
                    meta={"kind": "WIN", "window": window, "result": result},
                    is_win=True,
                )
                await wallet_service.house_settle(
                    -payout, game_key=game_key,
                    narration=f"Games payout · {game_key} W#{window}",
                )
                # Hierarchy commission (win-brokerage model) + referral — from house.
                await _distribute_win(bet.user_id, to_decimal(bet.amount), payout, game_key, cfg)
            settled += 1
            try:
                await publish(
                    f"user:{bet.user_id}:games",
                    {"type": "bet_result", "payload": {
                        "game": game_key, "window": window, "result": result,
                        "won": won, "payout": str(payout),
                    }},
                )
            except Exception:
                pass

    return settled
