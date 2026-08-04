"""Nifty + BTC Jackpot — predict-the-price pool games.

Bids are ranked by |predicted − locked_price| ascending; the top `top_winners`
share the day's pool by `prize_percentages` (ties sum + split equally). Winners
receive the FULL prize (house-funded); losers' stakes are already in the house.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from app.core.exceptions import (
    GameDisabledError,
    GameLimitExceededError,
    GameWindowClosedError,
)
from app.core.redis_client import publish
from app.models.games.bets import GameBetStatus, JackpotBank, JackpotBid
from app.models.games.settings import GameSettings
from app.services.games import price_resolver, wallet_service
from app.services.games.common import ist_datetime_for_day, parse_hms
from app.services.games.payout_math import jackpot_rank_and_prize
from app.utils.decimal_utils import quantize_money, to_decimal, to_decimal128
from app.utils.time_utils import now_ist, now_utc

logger = logging.getLogger(__name__)
_RESULT_GRACE_SEC = 15

# Predicted-price sanity ranges (spec §6.5).
_RANGES = {
    "niftyJackpot": (Decimal("1000"), Decimal("200000")),
    "btcJackpot": (Decimal("1"), Decimal("10000000")),
}


async def place_bid(
    user_id: PydanticObjectId, *, game_key: str, predicted_price
) -> JackpotBid:
    settings = await GameSettings.load_singleton()
    if not settings.games_enabled or settings.maintenance_mode:
        raise GameDisabledError("Games are currently unavailable")
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        raise GameDisabledError()

    now = now_ist()
    start_t = parse_hms(cfg.bidding_start_time)
    end_t = parse_hms(cfg.bidding_end_time)
    if not (start_t <= now.time() <= end_t):
        raise GameWindowClosedError("Bidding is closed")

    pred = to_decimal(predicted_price)
    lo, hi = _RANGES.get(game_key, (Decimal("0"), Decimal("100000000")))
    if pred < lo or pred > hi:
        raise GameLimitExceededError(f"Predicted price must be between {lo} and {hi}")

    day = now.strftime("%Y-%m-%d")
    todays = await JackpotBid.find(
        JackpotBid.user_id == user_id, JackpotBid.game_key == game_key, JackpotBid.bet_date == day
    ).count()
    if todays >= cfg.bids_per_day:
        raise GameLimitExceededError(f"Daily limit of {cfg.bids_per_day} bids reached")

    amt = quantize_money(to_decimal(cfg.ticket_price))

    await wallet_service.atomic_games_wallet_debit(
        user_id, amt, game_key=game_key,
        description=f"Jackpot bid · {game_key} · @{pred}",
        meta={"kind": "BET", "predicted": str(pred)},
    )
    await wallet_service.house_settle(amt, game_key=game_key, narration=f"Games stake in · {game_key}")

    bid = JackpotBid(
        user_id=user_id, game_key=game_key, amount=to_decimal128(amt),
        ticket_count=1, predicted_price=to_decimal128(pred), bet_date=day,
        status=GameBetStatus.PENDING,
    )
    await bid.insert()

    # Bump the per-day bank/pool.
    await JackpotBank.get_motor_collection().find_one_and_update(
        {"game_key": game_key, "bet_date": day},
        {
            "$inc": {"total_stake": to_decimal128(amt), "bids_count": 1},
            "$setOnInsert": {
                "game_key": game_key, "bet_date": day, "result_declared": False,
                "created_at": now_utc(), "updated_at": now_utc(),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_placed", "payload": {"game": game_key}})
    except Exception:
        pass
    return bid


async def modify_bid(user_id, bid_id: str, *, predicted_price) -> JackpotBid:
    """Change a live jackpot bid's predicted price (stake is fixed = 1 ticket).
    Jackpot supports MODIFY ONLY — no cancellation (operator spec)."""
    settings = await GameSettings.load_singleton()
    try:
        bid = await JackpotBid.get(PydanticObjectId(str(bid_id)))
    except Exception:
        bid = None
    if bid is None or bid.user_id != user_id:
        raise GameLimitExceededError("Bid not found")
    if bid.status != GameBetStatus.PENDING:
        raise GameWindowClosedError("This bid is already settled — can't change it")
    cfg = settings.games.get(bid.game_key)
    if cfg is None:
        raise GameDisabledError()
    now = now_ist()
    if not (parse_hms(cfg.bidding_start_time) <= now.time() <= parse_hms(cfg.bidding_end_time)):
        raise GameWindowClosedError("Bidding is closed — can't change the bid")

    pred = to_decimal(predicted_price)
    lo, hi = _RANGES.get(bid.game_key, (Decimal("0"), Decimal("100000000")))
    if pred < lo or pred > hi:
        raise GameLimitExceededError(f"Predicted price must be between {lo} and {hi}")

    bid.predicted_price = to_decimal128(pred)
    # Keep the original created_at so the tie-break (earliest bid wins) is unchanged
    # by a price edit — only the prediction moves, not the queue position.
    bid.updated_at = now_utc()
    await bid.save()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_modified", "payload": {"game": bid.game_key}})
    except Exception:
        pass
    return bid


async def declare_and_settle(game_key: str) -> int:
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(game_key)
    if cfg is None or not cfg.enabled:
        return 0

    now = now_ist()
    # The resolver's stability gate waits for the official clearing close, so no
    # extra fixed delay here — just the base result-time grace.
    grace_sec = _RESULT_GRACE_SEC
    result_t = parse_hms(cfg.result_time)

    # Record the day's result even with ZERO bids, so "Last 5 days results" shows
    # EVERY day — not only days someone bet. At/after result time, if no bank
    # exists for today, create a result-only bank (bids_count 0) with the locked
    # close. Bids close before result time, so this never races a real bid.
    today = now.strftime("%Y-%m-%d")
    result_dt_today = ist_datetime_for_day(today).replace(
        hour=result_t.hour, minute=result_t.minute, second=result_t.second
    )
    if now >= result_dt_today + timedelta(seconds=grace_sec):
        has_today = await JackpotBank.find_one(
            JackpotBank.game_key == game_key, JackpotBank.bet_date == today
        )
        if has_today is None:
            if game_key == "btcJackpot":
                locked_today = await price_resolver.resolve_btc_price_at(result_dt_today)
            elif not cfg.auto_result:
                # MANUAL mode — only the super-admin's typed value, never the feed.
                m = await price_resolver.manual_nifty_close(today, game_key)
                locked_today = quantize_money(m) if m is not None and m > 0 else None
            else:
                locked_today = await price_resolver.resolve_nifty_price_at(result_dt_today, strict=True, game_key=game_key)
            if locked_today is not None and locked_today > 0:
                try:
                    await JackpotBank(
                        game_key=game_key, bet_date=today, result_declared=True,
                        locked_price=to_decimal128(locked_today), bids_count=0,
                        total_stake=to_decimal128(Decimal("0")),
                    ).insert()
                except Exception:  # another tick already created it
                    pass

    banks = await JackpotBank.find(
        JackpotBank.game_key == game_key, JackpotBank.result_declared == False  # noqa: E712
    ).to_list()
    if not banks:
        return 0

    settled = 0
    for bank in banks:
        result_dt = ist_datetime_for_day(bank.bet_date).replace(
            hour=result_t.hour, minute=result_t.minute, second=result_t.second
        )
        if now < result_dt + timedelta(seconds=grace_sec):
            continue

        if game_key == "btcJackpot":
            locked = await price_resolver.resolve_btc_price_at(result_dt)
        elif not cfg.auto_result:
            # MANUAL mode — settle ONLY on the super-admin's typed value; never the
            # feed. Nothing typed yet → wait (don't auto-declare before entry).
            m = await price_resolver.manual_nifty_close(bank.bet_date, game_key)
            locked = quantize_money(m) if m is not None and m > 0 else None
        else:
            # strict=True → lock ONLY the official NSE close (the REST-quote
            # weighted-average clearing value), exactly like the Number game.
            # Without it the jackpot could lock the last-TRADED historical candle
            # (e.g. 24,081.10) while Number locked the official close (24,072.75)
            # for the SAME day — the two games then disagreed on the day's price.
            # None → wait/retry rather than lock a divergent value.
            locked = await price_resolver.resolve_nifty_price_at(result_dt, strict=True, game_key=game_key)
        if locked is None or locked <= 0:
            continue  # retry next tick

        # Atomic declare-claim so only one worker/tick settles this bank.
        claimed = await JackpotBank.get_motor_collection().find_one_and_update(
            {"_id": bank.id, "result_declared": False},
            {"$set": {"result_declared": True, "locked_price": to_decimal128(locked), "updated_at": now_utc()}},
        )
        if claimed is None:
            continue

        bids = await JackpotBid.find(
            JackpotBid.game_key == game_key, JackpotBid.bet_date == bank.bet_date,
            JackpotBid.status == GameBetStatus.PENDING,
        ).to_list()
        if not bids:
            continue

        pool = to_decimal(bank.total_stake)
        ranking = jackpot_rank_and_prize(
            [{"id": str(b.id), "predicted": to_decimal(b.predicted_price), "created_at": b.created_at} for b in bids],
            locked_price=locked,
            prize_percentages=cfg.prize_percentages,
            top_winners=cfg.top_winners,
            pool=pool,
        )
        for b in bids:
            r = ranking.get(str(b.id))
            if r is None:
                continue
            prize = to_decimal(r["prize"])
            b.rank = r["rank"]
            b.prize = to_decimal128(prize)
            if prize > 0:
                await wallet_service.atomic_games_wallet_credit(
                    b.user_id, prize, game_key=game_key,
                    description=f"Jackpot prize · {game_key} · Rank {r['rank']}",
                    meta={"kind": "WIN", "rank": r["rank"]}, is_win=True,
                )
                await wallet_service.house_settle(-prize, game_key=game_key, narration=f"Games payout · {game_key}")
                b.status = GameBetStatus.WON
                # 4-level %-of-WINNING split (hierarchy HELD + referrer games
                # wallet), funded from the house. Base = gross winning (the full
                # prize the winner receives from the bank).
                try:
                    from app.models.user import User
                    from app.services.games import hierarchy, referral

                    u = await User.get(b.user_id)
                    if u is not None:
                        win_amount = prize
                        if win_amount > 0:
                            await hierarchy.distribute_profit_split(u, win_amount, game_key, cfg)
                            await referral.credit_referral_on_win(u, win_amount, cfg, game_key=game_key)
                except Exception:  # noqa: BLE001
                    logger.exception("jackpot_distribute_failed bid=%s", b.id)
            else:
                b.status = GameBetStatus.LOST
            b.updated_at = now_utc()
            await b.save()
            settled += 1
            try:
                await publish(
                    f"user:{b.user_id}:games",
                    {"type": "bet_result", "payload": {
                        "game": game_key, "rank": r["rank"], "won": prize > 0,
                        "payout": str(b.prize)}},
                )
            except Exception:
                pass
    return settled
