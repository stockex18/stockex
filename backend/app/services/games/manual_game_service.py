"""Super-admin MANUAL game entry + reversal for the 3 Nifty games.

One typed NIFTY close drives all three games (Number, Jackpot, Bracket) — they
already resolve their result from the same close via
``price_resolver.manual_nifty_close`` (the ``niftyNumber`` GameManualResult).

- ``declare_day(day, close)`` — pin the manual close and settle all three.
- ``reverse_day(day)``        — undo a mis-declared settlement: claw back every
  credited leg (winner payout + hierarchy commission + referral reward,
  best-effort), reset all bets to PENDING, and clear the declared markers so a
  corrected close can be re-declared.
- ``preview_day(day)``        — current declared state + typed close for the UI.

Reversal is deterministic: each of the 3 games distributes via the SAME two
functions (``hierarchy.distribute_profit_split`` + ``referral.credit_referral_on_win``)
keyed off the winner's payout, so ``hierarchy.reverse_profit_split`` +
``referral.reverse_referral_on_win`` mirror them exactly.
"""

from __future__ import annotations

import logging

from app.models.games.bets import (
    BracketTrade,
    GameBetStatus,
    GameManualResult,
    GameResult,
    JackpotBank,
    JackpotBid,
    NumberBet,
)
from app.models.games.settings import GameSettings
from app.models.user import User
from app.services.games import hierarchy, number_service, referral, wallet_service
from app.utils.decimal_utils import ZERO, add, to_decimal, to_decimal128
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# The 3 Nifty games driven by one manual close. Order: settle Number first (its
# GameManualResult is the canonical close the resolver reads for all three).
NIFTY_MANUAL_GAMES = ["niftyNumber", "niftyJackpot", "niftyBracket"]
_CLOSE_KEY = "niftyNumber"


async def _reverse_one_win(user_id, payout, game_key: str, cfg, report: dict) -> None:
    """Reverse ONE win: claw back the winner payout (best-effort) + hierarchy +
    referral. Records any un-clawable payout in report["shortfalls"]."""
    pay = to_decimal(payout)
    if pay > ZERO:
        try:
            await wallet_service.atomic_games_wallet_debit(
                user_id, pay, game_key=game_key,
                description=f"Reverse {game_key} win (manual re-declare)",
                meta={"kind": "WIN_REVERSE"},
            )
            await wallet_service.house_settle(
                pay, game_key=game_key, narration=f"Reverse {game_key} win payout"
            )
        except Exception:
            # Winner already spent/withdrew the payout — flag it, keep going.
            report["shortfalls"].append({"user_id": str(user_id), "amount": str(pay)})
    user = await User.get(user_id)
    if user is not None:
        try:
            await hierarchy.reverse_profit_split(user, pay, game_key, cfg)
        except Exception:
            logger.exception("reverse_hierarchy_failed user=%s game=%s", user_id, game_key)
        try:
            await referral.reverse_referral_on_win(user, pay, cfg, game_key=game_key)
        except Exception:
            logger.exception("reverse_referral_failed user=%s game=%s", user_id, game_key)


async def reverse_game_day(game_key: str, day: str) -> dict:
    """Undo the day's settlement for one game and reset it to un-declared."""
    settings = await GameSettings.load_singleton()
    cfg = settings.games.get(game_key)
    report: dict = {"game": game_key, "won_reversed": 0, "payout_reversed": "0", "shortfalls": []}
    if cfg is None:
        return report

    total = ZERO
    if game_key == "niftyNumber":
        bets = await NumberBet.find({"game_key": game_key, "bet_date": day}).to_list()
        for b in bets:
            if b.status == GameBetStatus.WON:
                await _reverse_one_win(b.user_id, b.payout, game_key, cfg, report)
                total = add(total, to_decimal(b.payout))
                report["won_reversed"] += 1
            b.status = GameBetStatus.PENDING
            b.payout = to_decimal128(ZERO)
            b.result_number = None
            b.updated_at = now_utc()
            await b.save()
        await GameResult.find({"game_key": game_key, "day": day}).delete()

    elif game_key == "niftyJackpot":
        bids = await JackpotBid.find({"game_key": game_key, "bet_date": day}).to_list()
        for b in bids:
            if b.status == GameBetStatus.WON:
                await _reverse_one_win(b.user_id, b.prize, game_key, cfg, report)
                total = add(total, to_decimal(b.prize))
                report["won_reversed"] += 1
            b.status = GameBetStatus.PENDING
            b.prize = to_decimal128(ZERO)
            b.rank = None
            b.updated_at = now_utc()
            await b.save()
        bank = await JackpotBank.find_one({"game_key": game_key, "bet_date": day})
        if bank is not None:
            bank.result_declared = False
            bank.locked_price = None
            bank.updated_at = now_utc()
            await bank.save()

    elif game_key == "niftyBracket":
        trades = await BracketTrade.find({"game_key": game_key, "bet_date": day}).to_list()
        for t in trades:
            if t.status == GameBetStatus.WON:
                await _reverse_one_win(t.user_id, t.payout, game_key, cfg, report)
                total = add(total, to_decimal(t.payout))
                report["won_reversed"] += 1
            # Reset (incl. any trade stuck in transient "SETTLING").
            t.status = GameBetStatus.PENDING
            t.payout = to_decimal128(ZERO)
            t.result_price = None
            t.updated_at = now_utc()
            await t.save()

    # Drop this game's manual-close row so the auto-settle loop does NOT instantly
    # re-settle it on the same (wrong) value — the game is now truly un-declared.
    await GameManualResult.find(
        {"game_key": game_key, "day": day}
    ).delete()

    report["payout_reversed"] = str(total)
    logger.info("manual_reverse_game game=%s day=%s report=%s", game_key, day, report)
    return report


async def reverse_day(day: str) -> dict:
    """Reverse all three Nifty games for `day`. Also drops the pinned close so a
    corrected value resolves cleanly."""
    reports = [await reverse_game_day(g, day) for g in NIFTY_MANUAL_GAMES]
    # Clear any pinned official close for the day so re-declare re-pins fresh.
    try:
        from app.core.redis_client import cache_delete

        await cache_delete(f"games:nifty:close:{day}")
    except Exception:
        pass
    return {"day": day, "games": reports}


async def _set_manual_close(day: str, game_key: str, close, number: int) -> None:
    """Upsert ONE game's manual-close row. Each game reads its OWN row now, so
    per-game closes stay independent."""
    mr = await GameManualResult.find_one(
        GameManualResult.game_key == game_key, GameManualResult.day == day
    )
    if mr is None:
        mr = GameManualResult(
            game_key=game_key, day=day, result_number=number, close_price=to_decimal128(close)
        )
        await mr.insert()
    else:
        mr.result_number = number
        mr.close_price = to_decimal128(close)
        mr.updated_at = now_utc()
        await mr.save()


async def declare_day(day: str, close_price) -> dict:
    """Pin the manual NIFTY close for `day` and settle all three games on it."""
    close = to_decimal(close_price)
    if close <= ZERO:
        raise ValueError("close_price must be > 0")
    number = number_from_close(close)

    # Write the SAME close to all three per-game rows (each game reads its own).
    for g in NIFTY_MANUAL_GAMES:
        await _set_manual_close(day, g, close, number)

    await _drop_pins(day)

    # Settle each game — they resolve the manual close (market must be closed).
    settled: dict = {}
    for g in NIFTY_MANUAL_GAMES:
        try:
            settled[g] = await _settle_one(g)
        except Exception:
            logger.exception("manual_declare_settle_failed game=%s day=%s", g, day)
            settled[g] = "error"
    return {"day": day, "close_price": str(close), "number": number, "settled": settled}


async def _settle_one(game_key: str):
    """Settle ONE nifty game from the pinned manual close (market must be closed)."""
    if game_key == "niftyNumber":
        return await number_service.declare_and_settle(game_key)
    if game_key == "niftyJackpot":
        from app.services.games import jackpot_service

        return await jackpot_service.declare_and_settle(game_key)
    if game_key == "niftyBracket":
        from app.services.games import bracket_service

        return await bracket_service.declare_and_settle()
    raise ValueError(f"unknown game {game_key}")


async def _drop_pins(day: str) -> None:
    try:
        from app.core.redis_client import cache_delete

        await cache_delete(f"games:nifty:close:{day}")
        await cache_delete(f"games:nifty:lastcandle:{day}")
    except Exception:
        pass


async def declare_game(day: str, game_key: str, close_price) -> dict:
    """Declare/settle just ONE nifty game from a typed close — per-game control so
    a single wrong game can be fixed without touching the other two. Updates the
    canonical manual close (which every game's resolver reads) then settles only
    `game_key`; the already-settled siblings don't re-read it."""
    if game_key not in NIFTY_MANUAL_GAMES:
        raise ValueError("unknown game")
    close = to_decimal(close_price)
    if close <= ZERO:
        raise ValueError("close_price must be > 0")
    number = number_from_close(close)

    # Write ONLY this game's own manual-close row — the other two are untouched.
    await _set_manual_close(day, game_key, close, number)
    await _drop_pins(day)
    try:
        settled = await _settle_one(game_key)
    except Exception:
        logger.exception("manual_declare_game_failed game=%s day=%s", game_key, day)
        settled = "error"
    return {"day": day, "game_key": game_key, "close_price": str(close),
            "number": number, "settled": settled}


async def reverse_game(game_key: str, day: str) -> dict:
    """Reverse ONE nifty game and drop the day's pins so it can re-declare fresh."""
    if game_key not in NIFTY_MANUAL_GAMES:
        raise ValueError("unknown game")
    rep = await reverse_game_day(game_key, day)
    await _drop_pins(day)
    return rep


def number_from_close(close) -> int:
    return number_service.number_from_close("niftyNumber", close)


async def preview_day(day: str) -> dict:
    """Current declared state of the three games for `day` + the typed close."""
    mr = await GameManualResult.find_one(
        GameManualResult.game_key == _CLOSE_KEY, GameManualResult.day == day
    )
    manual_close = str(mr.close_price) if mr and mr.close_price is not None else None

    # Number
    num_res = await GameResult.find_one(
        {"game_key": "niftyNumber", "day": day, "window_number": None}
    )
    num_bets = await NumberBet.find({"game_key": "niftyNumber", "bet_date": day}).to_list()
    num_won = [b for b in num_bets if b.status == GameBetStatus.WON]

    # Jackpot
    bank = await JackpotBank.find_one({"game_key": "niftyJackpot", "bet_date": day})
    jp_bids = await JackpotBid.find({"game_key": "niftyJackpot", "bet_date": day}).to_list()
    jp_won = [b for b in jp_bids if b.status == GameBetStatus.WON]

    # Bracket
    br_trades = await BracketTrade.find({"game_key": "niftyBracket", "bet_date": day}).to_list()
    br_won = [t for t in br_trades if t.status == GameBetStatus.WON]

    def _sum(rows, field):
        return str(sum((to_decimal(getattr(r, field)) for r in rows), ZERO))

    return {
        "day": day,
        "manual_close": manual_close,
        "number_preview": number_from_close(to_decimal(manual_close)) if manual_close else None,
        "games": [
            {
                "game_key": "niftyNumber",
                "label": "Nifty Number",
                "declared": num_res is not None,
                "result": str(num_res.result_number) if num_res else None,
                "close_price": str(num_res.close_price) if num_res else None,
                "bets": len(num_bets),
                "winners": len(num_won),
                "payout": _sum(num_won, "payout"),
            },
            {
                "game_key": "niftyJackpot",
                "label": "Nifty Jackpot",
                "declared": bool(bank and bank.result_declared),
                "result": str(bank.locked_price) if bank and bank.locked_price is not None else None,
                "close_price": str(bank.locked_price) if bank and bank.locked_price is not None else None,
                "bets": len(jp_bids),
                "winners": len(jp_won),
                "payout": _sum(jp_won, "prize"),
            },
            {
                "game_key": "niftyBracket",
                "label": "Nifty Bracket",
                "declared": any(t.status != GameBetStatus.PENDING for t in br_trades),
                "result": None,
                "close_price": None,
                "bets": len(br_trades),
                "winners": len(br_won),
                "payout": _sum(br_won, "payout"),
            },
        ],
    }
