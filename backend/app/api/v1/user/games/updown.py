"""User Up/Down endpoints (Nifty + BTC share the same routes; gameId maps)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import CurrentUser
from app.core.exceptions import GameDisabledError, GameLimitExceededError, GameWindowClosedError
from app.models.games.bets import GameResult, UpDownBet
from app.schemas.common import APIResponse
from app.services.games import ids, updown_service

router = APIRouter(tags=["user-games-updown"])


class PlaceBet(BaseModel):
    gameId: str
    prediction: str  # "UP" | "DOWN"
    amount: float
    entryPrice: float
    windowNumber: int


class ModifyBet(BaseModel):
    prediction: str | None = None  # "UP" | "DOWN"
    amount: float | None = None


@router.post("/bet/place", response_model=APIResponse[dict])
async def place_bet(payload: PlaceBet, user: CurrentUser):
    key = ids.settings_key(payload.gameId)
    if key not in ("niftyUpDown", "btcUpDown"):
        raise HTTPException(status_code=404, detail="Unknown up/down game")
    bet = await updown_service.place_bet(
        user.id, game_key=key, prediction=payload.prediction,
        amount=payload.amount, entry_price=payload.entryPrice,
        window_number=payload.windowNumber,
    )
    return APIResponse(
        data={"id": str(bet.id), "window": bet.window_number, "status": bet.status.value},
        message="Bet placed",
    )


@router.patch("/bet/{bet_id}", response_model=APIResponse[dict])
async def modify_bet(bet_id: str, payload: ModifyBet, user: CurrentUser):
    """Modify a live Up/Down bet (change direction and/or stake, same window)."""
    try:
        bet = await updown_service.modify_bet(
            user.id, bet_id, prediction=payload.prediction, amount=payload.amount
        )
    except (GameWindowClosedError, GameDisabledError, GameLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(
        data={"id": str(bet.id), "prediction": bet.prediction.value, "amount": str(bet.amount)},
        message="Bet updated",
    )


@router.delete("/bet/{bet_id}", response_model=APIResponse[dict])
async def cancel_bet(bet_id: str, user: CurrentUser):
    """Cancel a live Up/Down bet and refund the stake."""
    try:
        res = await updown_service.cancel_bet(user.id, bet_id)
    except (GameWindowClosedError, GameDisabledError, GameLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(data=res, message="Bet cancelled — stake refunded")


@router.get("/bets/{game_id}", response_model=APIResponse[list])
async def my_bets(game_id: str, user: CurrentUser, limit: int = 50):
    key = ids.settings_key(game_id)
    rows = await UpDownBet.find(
        UpDownBet.user_id == user.id, UpDownBet.game_key == key
    ).sort("-created_at").limit(limit).to_list()
    return APIResponse(
        data=[
            {
                "id": str(b.id), "prediction": b.prediction.value, "amount": str(b.amount),
                "entry_price": str(b.entry_price), "window_number": b.window_number,
                "settlement_day": b.settlement_day, "status": b.status.value,
                "payout": str(b.payout), "result_price": str(b.result_price) if b.result_price else None,
                "created_at": b.created_at,
            }
            for b in rows
        ]
    )


@router.get("/results/{game_id}", response_model=APIResponse[list])
async def results(game_id: str, user: CurrentUser, limit: int = 50, day: str | None = None):
    key = ids.settings_key(game_id)
    q = {"game_key": key}
    if day:
        q["day"] = day
    rows = await GameResult.find(q).sort("-created_at").limit(limit).to_list()
    return APIResponse(
        data=[
            {
                "window_number": r.window_number, "day": r.day, "result": r.result,
                "open_price": str(r.open_price), "close_price": str(r.close_price),
                "price_source": r.price_source, "created_at": r.created_at,
            }
            for r in rows
        ]
    )
