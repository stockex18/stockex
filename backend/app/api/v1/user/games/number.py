"""User Number-game endpoints (Nifty + BTC)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import CurrentUser
from app.core.exceptions import GameDisabledError, GameLimitExceededError, GameWindowClosedError
from app.models.games.bets import GameResult, NumberBet
from app.schemas.common import APIResponse
from app.services.games import ids, number_service
from app.services.games.common import ist_day

router = APIRouter(prefix="/number", tags=["user-games-number"])


class NumberBetReq(BaseModel):
    gameId: str
    selectedNumbers: list[int]
    quantity: int = 1


class NumberModifyReq(BaseModel):
    selectedNumber: int | None = None
    quantity: int | None = None


@router.post("/bet", response_model=APIResponse[list])
async def place(payload: NumberBetReq, user: CurrentUser):
    key = ids.settings_key(payload.gameId)
    if key not in ("niftyNumber", "btcNumber"):
        raise HTTPException(status_code=404, detail="Unknown number game")
    placed = []
    for num in payload.selectedNumbers:
        bet = await number_service.place_bet(
            user.id, game_key=key, selected_number=int(num), quantity=payload.quantity
        )
        placed.append({"id": str(bet.id), "number": bet.selected_number})
    return APIResponse(data=placed, message="Bet placed")


@router.patch("/bet/{bet_id}", response_model=APIResponse[dict])
async def modify(bet_id: str, payload: NumberModifyReq, user: CurrentUser):
    """Modify a live number bet (change picked number and/or ticket quantity)."""
    try:
        bet = await number_service.modify_bet(
            user.id, bet_id, selected_number=payload.selectedNumber, quantity=payload.quantity
        )
    except (GameWindowClosedError, GameDisabledError, GameLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(
        data={"id": str(bet.id), "number": bet.selected_number,
              "quantity": bet.quantity, "amount": str(bet.amount)},
        message="Bet updated",
    )


@router.delete("/bet/{bet_id}", response_model=APIResponse[dict])
async def cancel(bet_id: str, user: CurrentUser):
    """Cancel a live number bet and refund the stake."""
    try:
        res = await number_service.cancel_bet(user.id, bet_id)
    except (GameWindowClosedError, GameDisabledError, GameLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(data=res, message="Bet cancelled — stake refunded")


@router.get("/today/{game_id}", response_model=APIResponse[dict])
async def today(game_id: str, user: CurrentUser):
    key = ids.settings_key(game_id)
    day = ist_day()
    rows = await NumberBet.find(
        NumberBet.user_id == user.id, NumberBet.game_key == key, NumberBet.bet_date == day
    ).to_list()
    return APIResponse(
        data={
            "bets": [
                {"id": str(b.id), "number": b.selected_number, "quantity": b.quantity,
                 "amount": str(b.amount), "status": b.status.value, "payout": str(b.payout)}
                for b in rows
            ]
        }
    )


@router.get("/daily-result/{game_id}", response_model=APIResponse[dict])
async def daily_result(game_id: str, user: CurrentUser, day: str | None = None):
    key = ids.settings_key(game_id)
    d = day or ist_day()
    r = await GameResult.find_one(
        GameResult.game_key == key, GameResult.day == d, GameResult.window_number == None  # noqa: E711
    )
    if r is None:
        return APIResponse(data={"declared": False})
    return APIResponse(
        data={"declared": True, "result_number": r.result_number,
              "closing_price": str(r.close_price), "day": r.day}
    )


@router.get("/last-5-days/{game_id}", response_model=APIResponse[list])
async def last_5_days(game_id: str, user: CurrentUser):
    """Last 5 declared daily results (winning number per day) for this game."""
    key = ids.settings_key(game_id)
    rows = await GameResult.find(
        GameResult.game_key == key, GameResult.window_number == None  # noqa: E711
    ).sort("-day").limit(5).to_list()
    return APIResponse(
        data=[
            {"day": r.day, "result_number": r.result_number, "closing_price": str(r.close_price)}
            for r in rows
        ]
    )
