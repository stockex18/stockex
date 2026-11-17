"""User games wallet — balance, main↔games transfer, ledger, today-net."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from fastapi import APIRouter

from app.core.dependencies import CurrentUser
from app.schemas.common import APIResponse
from app.services.games import wallet_service
from app.utils.decimal_utils import ZERO, add, sub, to_decimal

router = APIRouter(prefix="/wallet", tags=["user-games-wallet"])


class TransferIn(BaseModel):
    amount: float


class WithdrawReq(BaseModel):
    amount: float
    remark: str | None = None


@router.get("", response_model=APIResponse[dict])
async def get_wallet(user: CurrentUser):
    w = await wallet_service.get_or_create(user.id)
    return APIResponse(
        data={
            "balance": str(w.balance),
            "realized_pnl": str(w.realized_pnl),
            "today_realized_pnl": str(w.today_realized_pnl),
            "profit_blocked": w.profit_blocked,
        }
    )


@router.post("/transfer-in", response_model=APIResponse[dict])
async def transfer_in(payload: TransferIn, user: CurrentUser):
    res = await wallet_service.transfer_main_to_games(user.id, payload.amount)
    return APIResponse(data=res, message="Transferred to games wallet")


@router.post("/withdraw", response_model=APIResponse[dict])
async def withdraw(payload: WithdrawReq, user: CurrentUser):
    """Move free games balance back to MAIN — now INSTANT (no admin approval).
    A placed ticket's stake is already debited from the games balance, so only
    the FREE (uninvested) amount is withdrawable and it lands in main at once."""
    res = await wallet_service.transfer_games_to_main(user.id, payload.amount)
    return APIResponse(data={**res, "status": "COMPLETED"}, message="Transferred to main wallet")


@router.get("/ledger", response_model=APIResponse[list])
async def ledger(
    user: CurrentUser,
    *,
    gameId: str | None = None,
    # Clamped rather than validated, so an app build that asks for more than
    # 1,000 still gets an answer instead of an error.
    limit: int = 100,
    date: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    from app.services.games import ids as _ids

    game_key = _ids.settings_key(gameId) if gameId else None
    rows = await wallet_service.list_ledger(
        user.id,
        game_key=game_key,
        limit=max(1, min(limit, 1000)),
        day=date,
        from_date=from_date,
        to_date=to_date,
    )
    return APIResponse(
        data=[
            {
                "id": str(r.id),
                "entry_type": r.entry_type.value,
                "amount": str(r.amount),
                "balance_after": str(r.balance_after),
                "game_key": r.game_key,
                "description": r.description,
                "meta": r.meta,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    )


@router.get("/today-net", response_model=APIResponse[dict])
async def today_net(user: CurrentUser):
    from app.models.games.wallet import GamesLedgerEntryType, GamesWalletLedger
    from app.services.games.common import ist_day

    day = ist_day()
    # created_at is UTC; filter by IST day via ledger scan (cheap per user/day).
    rows = await GamesWalletLedger.find(
        GamesWalletLedger.owner_id == user.id
    ).sort("-created_at").limit(500).to_list()
    by_game: dict[str, str] = {}
    net: dict[str, object] = {}
    from app.utils.time_utils import to_ist

    for r in rows:
        if to_ist(r.created_at).strftime("%Y-%m-%d") != day:
            continue
        gk = r.game_key or "_transfer"
        cur = to_decimal(net.get(gk, ZERO))
        amt = to_decimal(r.amount)
        cur = add(cur, amt) if r.entry_type == GamesLedgerEntryType.CREDIT else sub(cur, amt)
        net[gk] = cur
    by_game = {k: str(v) for k, v in net.items()}
    return APIResponse(data={"byGame": by_game})
