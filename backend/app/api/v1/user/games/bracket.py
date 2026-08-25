"""User Nifty Bracket endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.dependencies import CurrentUser
from app.models.games.bets import BracketTrade, GameBetStatus
from app.schemas.common import APIResponse
from app.services.games import bracket_service, price_resolver
from app.services.games.common import ist_day

router = APIRouter(prefix="/bracket", tags=["user-games-bracket"])


class BracketReq(BaseModel):
    prediction: str  # BUY | SELL
    amount: float
    entryPrice: float


def _ser(t: BracketTrade) -> dict:
    return {
        "id": str(t.id), "prediction": t.prediction.value, "amount": str(t.amount),
        "entry_price": str(t.entry_price), "upper_target": str(t.upper_target),
        "lower_target": str(t.lower_target), "expires_at": t.expires_at,
        "status": t.status.value, "payout": str(t.payout),
        "result_price": str(t.result_price) if t.result_price else None,
        "created_at": t.created_at,
    }


@router.post("/trade", response_model=APIResponse[dict])
async def trade(payload: BracketReq, user: CurrentUser):
    t = await bracket_service.place_bet(
        user.id, prediction=payload.prediction, amount=payload.amount, entry_price=payload.entryPrice
    )
    return APIResponse(data=_ser(t), message="Bracket placed")


@router.get("/active", response_model=APIResponse[list])
async def active(user: CurrentUser):
    rows = await BracketTrade.find(
        BracketTrade.user_id == user.id, BracketTrade.status == GameBetStatus.PENDING
    ).sort("-created_at").to_list()
    return APIResponse(data=[_ser(t) for t in rows])


@router.get("/history", response_model=APIResponse[list])
async def history(user: CurrentUser, limit: int = 50):
    rows = await BracketTrade.find(BracketTrade.user_id == user.id).sort("-created_at").limit(limit).to_list()
    return APIResponse(data=[_ser(t) for t in rows])


@router.get("/recent-results", response_model=APIResponse[list])
async def recent_results(user: CurrentUser, limit: int = 5):
    """Last N SESSION results for the Nifty Bracket — GLOBAL, so every player sees
    the recent outcomes even before their own trades settle.

    All same-day brackets resolve together at the one official session-close price,
    so we collapse the resolved trades to a single close per IST day. `direction`
    is that close vs the previous session's close (UP/DOWN/FLAT) for colouring.
    """
    n = max(1, min(int(limit or 5), 30))

    # What players were actually SETTLED on, per day. This is the authoritative
    # number for a day that traded — the bracket settles on the last 1-minute
    # candle close, which can differ by a tick from the daily candle's close.
    rows = (
        await BracketTrade.find({"status": {"$ne": GameBetStatus.PENDING.value}})
        .sort("-created_at")
        .limit(1500)
        .to_list()
    )
    settled: dict[str, str] = {}
    for t in rows:
        if t.result_price is None:
            continue
        d = ist_day(t.created_at)
        if d not in settled:
            settled[d] = str(t.result_price)

    # The SESSIONS themselves. A close exists whether or not anyone traded it,
    # so building the strip from player activity left it blank on a quiet day
    # and near-empty on a new game. One extra session is pulled so the oldest
    # row still has a previous close to take its direction from.
    sessions = await price_resolver.recent_nifty_session_closes(n + 1)
    if sessions:
        closes = [(d, settled.get(d, str(c))) for d, c in sessions]
    else:
        # Feed can't answer — fall back to what we settled, rather than nothing.
        closes = [(d, settled[d]) for d in sorted(settled, reverse=True)]

    out: list[dict] = []
    for i, (d, close) in enumerate(closes[:n]):
        direction = None
        if i + 1 < len(closes):  # the next entry is the previous session
            prev = float(closes[i + 1][1])
            cur = float(close)
            direction = "UP" if cur > prev else ("DOWN" if cur < prev else "FLAT")
        out.append({
            "day": d,
            "close_price": close,
            "direction": direction,
            # True once the game has actually settled that day — lets the UI
            # tell a declared result from a session that simply had no play.
            "settled": d in settled,
        })
    return APIResponse(data=out)
