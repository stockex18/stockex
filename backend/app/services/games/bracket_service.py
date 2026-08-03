"""Nifty Bracket — BUY/SELL band trade placement + expiry resolution.

Server builds a band around live spot at placement:
  upper = centre + gap, lower = centre − gap   (centre = live spot if anchored)
Resolution rule (`bracket_session_close_rule`):
  • directionVsEntry: BUY wins if LTP > entry; SELL wins if LTP < entry.
  • breakPastBands:   BUY wins if LTP > upper; SELL wins if LTP < lower.
Model A payout (win_multiplier, default 1.9×). Loss = full stake.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone
from decimal import Decimal

from beanie import PydanticObjectId

from app.core.exceptions import (
    GameDisabledError,
    GameLimitExceededError,
    GameWindowClosedError,
)
from app.core.redis_client import publish
from app.models.games.bets import BracketPrediction, BracketTrade, GameBetStatus
from app.models.games.settings import GameSettings
from app.services.games import price_resolver, wallet_service
from app.services.games.common import ist_datetime_for_day, parse_hms
from app.utils.decimal_utils import quantize_money, to_decimal, to_decimal128
from app.utils.time_utils import now_ist, now_utc

logger = logging.getLogger(__name__)
GAME_KEY = "niftyBracket"
_MAX_PER_TICK = 200
# Wait this many seconds AFTER the session close before resolving, so the final
# 15:29→15:30 candle is closed + published (operator: "check from 15:30:30").
_BRACKET_RESULT_GRACE_SEC = 30


async def place_bet(
    user_id: PydanticObjectId, *, prediction: str, amount, entry_price
) -> BracketTrade:
    settings = await GameSettings.load_singleton()
    if not settings.games_enabled or settings.maintenance_mode:
        raise GameDisabledError("Games are currently unavailable")
    cfg = settings.games.get(GAME_KEY)
    if cfg is None or not cfg.enabled:
        raise GameDisabledError()

    now = now_ist()
    start_t = parse_hms(cfg.bidding_start_time)
    end_t = parse_hms(cfg.bidding_end_time)
    if not (start_t <= now.time() <= end_t):
        raise GameWindowClosedError("Bidding is closed")

    amt = quantize_money(to_decimal(amount))
    tp = to_decimal(cfg.ticket_price)
    if tp <= 0:
        raise GameLimitExceededError("Invalid ticket price")
    tickets = int((amt / tp).to_integral_value())
    if tickets < cfg.min_tickets or tickets > cfg.max_tickets:
        raise GameLimitExceededError(
            f"Tickets must be between {cfg.min_tickets} and {cfg.max_tickets}"
        )

    pred = BracketPrediction(prediction.upper())

    # Band around the live spot.
    spot = await price_resolver.nifty_ltp()
    centre = spot if (spot and cfg.bracket_anchor_to_spot) else to_decimal(entry_price)
    if centre is None or centre <= 0:
        raise GameWindowClosedError("Live price unavailable")
    if cfg.bracket_gap_type == "percentage":
        gap = centre * to_decimal(cfg.bracket_gap_percent) / to_decimal(100)
    else:
        gap = to_decimal(cfg.bracket_gap)
    upper = quantize_money(centre + gap)
    lower = quantize_money(centre - gap)
    # Entry is the BRACKET EDGE for the chosen side, not the raw spot: UP enters
    # at the up-above band (centre + gap), DOWN at the down-below band
    # (centre − gap). So two opposite bets placed at the SAME instant sit a full
    # spread (2 × gap) apart instead of showing the identical price, and a win
    # requires price to break PAST the bracket rather than merely tick the right
    # way. directionVsEntry then coincides with breakPastBands.
    side_entry = upper if pred == BracketPrediction.BUY else lower
    # All bracket bets resolve TOGETHER at the session close (result_time) —
    # one fixed result time per day, NOT a per-trade 5-min timer. (User spec:
    # "Nifty Bracket … result @ 15:30:00".)
    result_t = parse_hms(cfg.result_time)
    expires_at = (
        ist_datetime_for_day(now.strftime("%Y-%m-%d"))
        .replace(hour=result_t.hour, minute=result_t.minute, second=result_t.second, microsecond=0)
        .astimezone(timezone.utc)
    )

    await wallet_service.atomic_games_wallet_debit(
        user_id, amt, game_key=GAME_KEY,
        description=f"Bracket · {pred.value} · 🪙{amt}",
        meta={"kind": "BET", "prediction": pred.value},
    )
    await wallet_service.house_settle(amt, game_key=GAME_KEY, narration="Games stake in · bracket")

    trade = BracketTrade(
        user_id=user_id, game_key=GAME_KEY, prediction=pred,
        amount=to_decimal128(amt), entry_price=to_decimal128(side_entry),
        spot_at_order=to_decimal128(centre), upper_target=to_decimal128(upper),
        lower_target=to_decimal128(lower), expires_at=expires_at,
        bet_date=now.strftime("%Y-%m-%d"), status=GameBetStatus.PENDING,
    )
    await trade.insert()
    try:
        await publish(f"user:{user_id}:games", {"type": "bet_placed", "payload": {"game": GAME_KEY}})
    except Exception:
        pass
    return trade


def _won(trade: BracketTrade, ltp, rule: str) -> bool:
    ltp = to_decimal(ltp)
    entry = to_decimal(trade.entry_price)
    if rule == "breakPastBands":
        if trade.prediction == BracketPrediction.BUY:
            return ltp > to_decimal(trade.upper_target)
        return ltp < to_decimal(trade.lower_target)
    # directionVsEntry (default)
    if trade.prediction == BracketPrediction.BUY:
        return ltp > entry
    return ltp < entry


async def declare_and_settle() -> int:
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(GAME_KEY)
    if cfg is None or not cfg.enabled:
        return 0

    # The resolver's stability gate waits for the official clearing close before
    # it returns a value, so we resolve as soon as trades expire and let the
    # resolver hold until the clearing lands.
    due = await BracketTrade.find(
        BracketTrade.status == GameBetStatus.PENDING,
        BracketTrade.expires_at <= now_utc(),
    ).limit(_MAX_PER_TICK).to_list()
    if not due:
        return 0

    # Resolve on the LAST session candle's CLOSE — the exact "C" value the Zerodha
    # chart shows for the final 15:29→15:30 candle (operator spec: settle on the
    # last candle's closing). All same-day trades share the result time; resolve
    # once at the latest expiry.
    result_dt = max(t.expires_at for t in due)
    # Only START checking 30s AFTER the session close (i.e. from 15:30:30) so the
    # final 15:29→15:30 candle is fully closed AND published before we read it.
    # Until then, wait (retry next tick) — never settle on a mid-forming candle.
    if now_utc() < result_dt + timedelta(seconds=_BRACKET_RESULT_GRACE_SEC):
        return 0
    # Last-candle close is drawn from Kite HISTORICAL (REST) — immune to a frozen
    # WS live tick — and matches the chart exactly. None → retry next tick until
    # the correct close lands (or the super-admin types it in Manual Game Entry),
    # so a wrong / stale result is never declared.
    ltp = await price_resolver.resolve_nifty_last_candle_close(result_dt, game_key="niftyBracket")
    if ltp is None or ltp <= 0:
        return 0

    settled = 0
    for trade in due:
        # Atomic status claim so a re-entrant tick can't double-settle.
        claimed = await BracketTrade.get_motor_collection().find_one_and_update(
            {"_id": trade.id, "status": GameBetStatus.PENDING.value},
            {"$set": {"status": "SETTLING", "updated_at": now_utc()}},
        )
        if claimed is None:
            continue
        won = _won(trade, ltp, cfg.bracket_session_close_rule)
        if won:
            payout = quantize_money(to_decimal(trade.amount) * to_decimal(cfg.win_multiplier))
            await wallet_service.atomic_games_wallet_credit(
                trade.user_id, payout, game_key=GAME_KEY,
                description=f"Bracket win · {trade.prediction.value}",
                meta={"kind": "WIN"}, is_win=True,
            )
            await wallet_service.house_settle(-payout, game_key=GAME_KEY, narration="Games payout · bracket")
            trade.status = GameBetStatus.WON
            trade.payout = to_decimal128(payout)
            # 4-level %-of-WINNING split (hierarchy HELD + referrer games
            # wallet), funded from the house. Base = gross winning (full payout).
            try:
                from app.models.user import User
                from app.services.games import hierarchy, referral

                u = await User.get(trade.user_id)
                if u is not None:
                    win_amount = to_decimal(payout)
                    if win_amount > 0:
                        await hierarchy.distribute_profit_split(u, win_amount, GAME_KEY, cfg)
                        await referral.credit_referral_on_win(u, win_amount, cfg, game_key=GAME_KEY)
            except Exception:  # noqa: BLE001
                logger.exception("bracket_distribute_win_failed trade=%s", trade.id)
        else:
            trade.status = GameBetStatus.LOST
            trade.payout = to_decimal128(Decimal("0"))
        trade.result_price = to_decimal128(ltp)
        trade.updated_at = now_utc()
        await trade.save()
        settled += 1
        try:
            await publish(
                f"user:{trade.user_id}:games",
                {"type": "bet_result", "payload": {
                    "game": GAME_KEY, "won": won, "payout": str(trade.payout)}},
            )
        except Exception:
            pass
    return settled
