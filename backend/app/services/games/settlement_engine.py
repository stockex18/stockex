"""Games auto-settlement engine — 3 leader-only background loops.

  • games_general_tick_loop (30s) — Nifty Up/Down, Bracket, Number (both),
    Nifty Jackpot.
  • btc_updown_fast_loop (5s)     — BTC Up/Down (fast publish).
  • btc_jackpot_loop (1s)         — BTC Jackpot lock + declare.

Each loop is wrapped in `_supervise` + `_leader_only` at the main.py lifespan
so exactly one worker runs it. Per-loop single-flight is guaranteed by the
sequential `while` body; every declare path is independently idempotent
(UpDownWindowSettlement unique index / GameResult / bank.result_declared), so
a duplicate fire is a safe no-op. All declares are wrapped so one game's error
never stops the others.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.games import (
    bracket_service,
    jackpot_service,
    number_service,
    updown_service,
)

logger = logging.getLogger(__name__)

_general_stop = False
_btc_updown_stop = False
_btc_jackpot_stop = False


def stop_games_loops() -> None:
    global _general_stop, _btc_updown_stop, _btc_jackpot_stop
    _general_stop = True
    _btc_updown_stop = True
    _btc_jackpot_stop = True


async def _safe(label: str, coro) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001 — one game's failure must not stop others
        logger.exception("games_settle_failed %s", label)


# ── 5 PM auto-cancel for NIFTY games ────────────────────────────────────
# Every NIFTY game resolves by ~15:45 IST. Anything still PENDING after 17:00
# never resolved (holiday / no price / stuck feed), so we CANCEL + REFUND it so
# no user's stake is stranded. BTC games run 24×7 and are untouched.
_NIFTY_GAME_KEYS = ("niftyUpDown", "niftyNumber", "niftyBracket", "niftyJackpot")
_CANCEL_HOUR = 17  # 5 PM IST


async def cancel_stale_nifty_bets() -> int:
    """After 5 PM IST refund every still-PENDING NIFTY game bet (stake back to
    the games wallet, house returns what it collected) and mark it CANCELLED.
    Atomic status-claim so it can't race the settle loop into a double credit."""
    from app.models.games.bets import (
        BracketTrade,
        GameBetStatus,
        JackpotBid,
        NumberBet,
        UpDownBet,
    )
    from app.services.games import wallet_service as gw
    from app.utils.decimal_utils import to_decimal
    from app.utils.time_utils import now_ist, now_utc

    if now_ist().hour < _CANCEL_HOUR:
        return 0

    cancelled = 0
    for Model in (UpDownBet, NumberBet, BracketTrade, JackpotBid):
        coll = Model.get_motor_collection()
        pend = await Model.find(
            {"game_key": {"$in": list(_NIFTY_GAME_KEYS)}, "status": GameBetStatus.PENDING.value}
        ).to_list()
        for bet in pend:
            claimed = await coll.find_one_and_update(
                {"_id": bet.id, "status": GameBetStatus.PENDING.value},
                {"$set": {"status": GameBetStatus.CANCELLED.value, "updated_at": now_utc()}},
            )
            if claimed is None:
                continue  # settled/cancelled by another pass
            amt = to_decimal(bet.amount)
            if amt > 0:
                try:
                    await gw.atomic_games_wallet_credit(
                        bet.user_id, amt, game_key=bet.game_key,
                        description="Refund — game cancelled at 5 PM (no result)",
                        meta={"kind": "REFUND", "reason": "auto_cancel_5pm"},
                    )
                    await gw.house_settle(
                        -amt, game_key=bet.game_key,
                        narration="Refund cancelled game bet (5 PM)",
                        user_id=bet.user_id,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("cancel_refund_failed bet=%s", bet.id)
            cancelled += 1
    if cancelled:
        logger.info("cancel_stale_nifty_bets refunded=%s", cancelled)
    return cancelled


async def games_general_tick_loop(interval_sec: float = 30.0) -> None:
    global _general_stop
    _general_stop = False
    logger.info("games_general_tick_loop_started")
    # Backfill the number-game daily-results history once on startup, then every
    # ~2 h. This heals any gap (a day nobody bet on, or a worker restart across
    # result time) so the user's "Last N days results" strip has no holes.
    _backfill_every = max(1, int(7200 / interval_sec))
    _tick = 0
    while not _general_stop:
        await _safe("niftyUpDown", updown_service.declare_and_settle("niftyUpDown"))
        await _safe("niftyBracket", bracket_service.declare_and_settle())
        await _safe("niftyNumber", number_service.declare_and_settle("niftyNumber"))
        await _safe("btcNumber", number_service.declare_and_settle("btcNumber"))
        await _safe("niftyJackpot", jackpot_service.declare_and_settle("niftyJackpot"))
        # 5 PM sweep — refund any NIFTY bet that never resolved (no-op before 5 PM).
        await _safe("cancel5pm", cancel_stale_nifty_bets())
        if _tick % _backfill_every == 0:
            await _safe("backfillNiftyNumber", number_service.backfill_recent_results("niftyNumber"))
            await _safe("backfillBtcNumber", number_service.backfill_recent_results("btcNumber"))
        _tick += 1
        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            return


async def btc_updown_fast_loop(interval_sec: float = 5.0) -> None:
    global _btc_updown_stop
    _btc_updown_stop = False
    logger.info("games_btc_updown_fast_loop_started")
    while not _btc_updown_stop:
        await _safe("btcUpDown", updown_service.declare_and_settle("btcUpDown"))
        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            return


async def btc_jackpot_loop(interval_sec: float = 1.0) -> None:
    global _btc_jackpot_stop
    _btc_jackpot_stop = False
    logger.info("games_btc_jackpot_loop_started")
    while not _btc_jackpot_stop:
        await _safe("btcJackpot", jackpot_service.declare_and_settle("btcJackpot"))
        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            return
