"""User Jackpot endpoints (Nifty + BTC)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import CurrentUser
from app.core.exceptions import GameDisabledError, GameLimitExceededError, GameWindowClosedError
from app.models.games.bets import GameBetStatus, JackpotBank, JackpotBid
from app.models.games.settings import GameSettings
from app.schemas.common import APIResponse
from app.services.games import ids, jackpot_service, price_resolver
from app.services.games.common import ist_day
from app.services.games.payout_math import jackpot_rank_and_prize
from app.utils.decimal_utils import to_decimal

router = APIRouter(prefix="/jackpot", tags=["user-games-jackpot"])


class BidReq(BaseModel):
    gameId: str
    predictedPrice: float


class BidModifyReq(BaseModel):
    predictedPrice: float


@router.post("/bid", response_model=APIResponse[dict])
async def bid(payload: BidReq, user: CurrentUser):
    key = ids.settings_key(payload.gameId)
    if key not in ("niftyJackpot", "btcJackpot"):
        raise HTTPException(status_code=404, detail="Unknown jackpot game")
    b = await jackpot_service.place_bid(user.id, game_key=key, predicted_price=payload.predictedPrice)
    return APIResponse(data={"id": str(b.id), "predicted": str(b.predicted_price)}, message="Bid placed")


@router.patch("/bid/{bid_id}", response_model=APIResponse[dict])
async def modify(bid_id: str, payload: BidModifyReq, user: CurrentUser):
    """Modify a live jackpot bid's predicted price. Jackpot = modify only (no cancel)."""
    try:
        b = await jackpot_service.modify_bid(user.id, bid_id, predicted_price=payload.predictedPrice)
    except (GameWindowClosedError, GameDisabledError, GameLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(data={"id": str(b.id), "predicted": str(b.predicted_price)}, message="Bid updated")


@router.get("/today/{game_id}", response_model=APIResponse[dict])
async def today(game_id: str, user: CurrentUser):
    key = ids.settings_key(game_id)
    day = ist_day()
    rows = await JackpotBid.find(
        JackpotBid.user_id == user.id, JackpotBid.game_key == key, JackpotBid.bet_date == day
    ).to_list()
    bank = await JackpotBank.find_one(JackpotBank.game_key == key, JackpotBank.bet_date == day)
    return APIResponse(
        data={
            "bids": [
                {"id": str(b.id), "predicted": str(b.predicted_price), "status": b.status.value,
                 "rank": b.rank, "prize": str(b.prize),
                 # amount staked + the exact millisecond-precise placement time
                 # so the user sees WHEN they bet + HOW MUCH (ties break by this).
                 "amount": str(b.amount), "tickets": b.ticket_count,
                 "created_at": b.created_at.isoformat() if b.created_at else None}
                for b in rows
            ],
            "totalPool": str(bank.total_stake) if bank else "0",
            "locked": str(bank.locked_price) if bank and bank.locked_price else None,
            "resultDeclared": bool(bank.result_declared) if bank else False,
        }
    )


@router.get("/leaderboard/{game_id}", response_model=APIResponse[dict])
async def leaderboard(game_id: str, user: CurrentUser, limit: int = 20):
    key = ids.settings_key(game_id)
    if key not in ("niftyJackpot", "btcJackpot"):
        raise HTTPException(status_code=404, detail="Unknown jackpot game")
    day = ist_day()
    settings = await GameSettings.load_singleton()
    cfg = settings.games[key]
    bank = await JackpotBank.find_one(JackpotBank.game_key == key, JackpotBank.bet_date == day)
    bids = await JackpotBid.find(JackpotBid.game_key == key, JackpotBid.bet_date == day).to_list()

    # Reference price: locked (official) if declared, else current live spot.
    # Use the DISPLAY resolver for NIFTY (`nifty_ltp_display`) — it always returns
    # a value from a persistent last-known cache. The settlement `nifty_ltp()`
    # returns None off-tick / on a non-leader worker, which made the leaderboard
    # momentarily compute `ref=None` → an EMPTY board even though bids exist (the
    # "leaderboard shows then vanishes" flicker).
    if bank and bank.locked_price:
        ref = to_decimal(bank.locked_price)
        official = True
    else:
        ref = await (price_resolver.btc_ltp() if key == "btcJackpot" else price_resolver.nifty_ltp_display())
        official = False
    pool = to_decimal(bank.total_stake) if bank else to_decimal(0)

    board = []
    my_rank = None
    if ref and bids:
        ranking = jackpot_rank_and_prize(
            [{"id": str(b.id), "predicted": to_decimal(b.predicted_price), "created_at": b.created_at} for b in bids],
            locked_price=ref, prize_percentages=cfg.prize_percentages,
            top_winners=cfg.top_winners, pool=pool,
        )
        by_id = {str(b.id): b for b in bids}
        ordered = sorted(ranking.items(), key=lambda kv: kv[1]["rank"])
        for bid_id, r in ordered[:limit]:
            b = by_id[bid_id]
            entry = {
                "rank": r["rank"], "predicted": str(b.predicted_price),
                "projectedPrize": str(r["prize"]), "isMe": b.user_id == user.id,
                # Placement time (ms-precise) — the tie-breaker: an earlier bid
                # wins a tie. Shown per leaderboard row.
                "placed_at": b.created_at.isoformat() if b.created_at else None,
            }
            board.append(entry)
            if b.user_id == user.id:
                my_rank = r["rank"]
        if my_rank is None:
            for bid_id, r in ranking.items():
                if by_id[bid_id].user_id == user.id:
                    my_rank = r["rank"]
                    break
    return APIResponse(
        data={
            "leaderboard": board, "referenceSpot": str(ref) if ref else None,
            "official": official, "myRank": my_rank, "totalPool": str(pool),
        }
    )


@router.get("/last-5-days/{game_id}", response_model=APIResponse[list])
async def last_5_days(game_id: str, user: CurrentUser):
    """Last 5 declared daily results for a jackpot game — the settlement close
    (`locked_price`) plus that day's winning bid, for the "Last 5 days results"
    strip. Mirrors the Number game's history strip."""
    key = ids.settings_key(game_id)
    banks = await JackpotBank.find(
        JackpotBank.game_key == key, JackpotBank.result_declared == True  # noqa: E712
    ).sort("-bet_date").limit(5).to_list()
    out = []
    for b in banks:
        winner = await JackpotBid.find_one(
            JackpotBid.game_key == key, JackpotBid.bet_date == b.bet_date, JackpotBid.rank == 1
        )
        out.append(
            {
                "day": b.bet_date,
                "close_price": str(b.locked_price) if b.locked_price is not None else None,
                "bids_count": b.bids_count,
                "winner_predicted": str(winner.predicted_price) if winner else None,
                "winner_prize": str(winner.prize) if winner else None,
            }
        )
    return APIResponse(data=out)


@router.get("/history/{game_id}", response_model=APIResponse[list])
async def history(game_id: str, user: CurrentUser, limit: int = 50):
    key = ids.settings_key(game_id)
    rows = await JackpotBid.find(
        JackpotBid.user_id == user.id, JackpotBid.game_key == key
    ).sort("-created_at").limit(limit).to_list()
    return APIResponse(
        data=[
            {"id": str(b.id), "predicted": str(b.predicted_price), "bet_date": b.bet_date,
             "status": b.status.value, "rank": b.rank, "prize": str(b.prize)}
            for b in rows
        ]
    )
