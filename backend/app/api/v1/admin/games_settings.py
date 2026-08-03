"""Admin (SUPER_ADMIN only) — Game settings config + games→main approvals."""

from __future__ import annotations

from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException

from app.core.dependencies import SuperAdmin
from app.models.games.settings import GAME_KEYS, GameConfig, GameSettings
from app.models.games.transfer import GamesWithdrawalRequest, GamesWithdrawalStatus
from app.schemas.common import APIResponse
from app.services.games import ids, wallet_service

router = APIRouter(prefix="/games", tags=["admin-games"])

# Global scalar fields an admin may set via PUT /games/settings.
_GLOBAL_FIELDS = {
    "games_enabled", "maintenance_mode", "maintenance_message", "token_value",
    "platform_commission", "global_min_tickets", "global_max_tickets",
    "daily_bet_limit", "daily_win_limit", "game_position_expiry_grace_seconds",
}


def _serialize(s: GameSettings) -> dict[str, Any]:
    return s.model_dump(mode="json", exclude={"id", "revision_id"})


@router.get("/settings", response_model=APIResponse[dict])
async def get_settings(_: SuperAdmin):
    s = await GameSettings.load_singleton()
    return APIResponse(data=_serialize(s))


@router.get("/settings/live-details", response_model=APIResponse[dict])
async def live_details(_: SuperAdmin):
    from app.services.games import price_resolver

    s = await GameSettings.load_singleton()
    nifty = await price_resolver.nifty_ltp()
    btc = await price_resolver.btc_ltp()
    return APIResponse(
        data={
            "settings": _serialize(s),
            "live": {"nifty": str(nifty) if nifty else None, "btc": str(btc) if btc else None},
        }
    )


@router.put("/settings", response_model=APIResponse[dict])
async def update_settings(payload: dict, _: SuperAdmin):
    s = await GameSettings.load_singleton()
    for k, v in payload.items():
        if k in _GLOBAL_FIELDS:
            setattr(s, k, v)
        elif k == "profit_distribution" and isinstance(v, dict):
            s.profit_distribution = s.profit_distribution.model_copy(update=v)
    await s.save()
    return APIResponse(data=_serialize(s), message="Settings updated")


@router.put("/settings/game/{game_id}", response_model=APIResponse[dict])
async def update_game(game_id: str, payload: dict, _: SuperAdmin):
    key = ids.settings_key(game_id)
    if key is None or key not in GAME_KEYS:
        raise HTTPException(status_code=404, detail="Unknown game")
    s = await GameSettings.load_singleton()
    current = s.games.get(key) or GameConfig()
    merged = current.model_copy(update={k: v for k, v in payload.items() if k in GameConfig.model_fields})
    s.games[key] = merged
    await s.save()
    return APIResponse(data=merged.model_dump(mode="json"), message="Game updated")


@router.patch("/settings/game/{game_id}/toggle", response_model=APIResponse[dict])
async def toggle_game(game_id: str, payload: dict, _: SuperAdmin):
    key = ids.settings_key(game_id)
    if key is None or key not in GAME_KEYS:
        raise HTTPException(status_code=404, detail="Unknown game")
    s = await GameSettings.load_singleton()
    cfg = s.games.get(key) or GameConfig()
    cfg.enabled = bool(payload.get("enabled", not cfg.enabled))
    s.games[key] = cfg
    await s.save()
    return APIResponse(data={"game": key, "enabled": cfg.enabled})


@router.patch("/settings/toggle-all", response_model=APIResponse[dict])
async def toggle_all(payload: dict, _: SuperAdmin):
    s = await GameSettings.load_singleton()
    enabled = bool(payload.get("enabled", True))
    s.games_enabled = enabled
    await s.save()
    return APIResponse(data={"games_enabled": enabled})


@router.patch("/settings/maintenance", response_model=APIResponse[dict])
async def set_maintenance(payload: dict, _: SuperAdmin):
    s = await GameSettings.load_singleton()
    s.maintenance_mode = bool(payload.get("maintenance_mode", True))
    if payload.get("maintenance_message"):
        s.maintenance_message = str(payload["maintenance_message"])
    await s.save()
    return APIResponse(data={"maintenance_mode": s.maintenance_mode})


# ── Manual daily result override (number games) ──────────────────────
# The super-admin can turn a number game's `auto_result` OFF and type the
# day's result by hand. These endpoints back the "Result Control" card. The
# toggle itself saves through PUT /settings/game/{id} (auto_result is a
# GameConfig field); here we manage the per-day typed value + expose what the
# auto (Zerodha) result would be right now, side by side.
_NUMBER_GAMES = {"niftyNumber", "btcNumber"}


def _result_dt_for_today(cfg):
    from app.services.games.common import ist_datetime_for_day, ist_day, parse_hms

    t = parse_hms(cfg.result_time)
    day = ist_day()
    return day, ist_datetime_for_day(day).replace(hour=t.hour, minute=t.minute, second=t.second)


async def _auto_preview(game_key: str, cfg) -> dict:
    """What the AUTO (Zerodha) path would give right now — regardless of the
    toggle — so the admin sees the live-derived result next to the manual one."""
    from app.services.games import number_service, price_resolver

    _, result_dt = _result_dt_for_today(cfg)
    try:
        if game_key == "btcNumber":
            close = await price_resolver.resolve_btc_price_at(result_dt)
        else:
            close = await price_resolver.resolve_nifty_price_at(result_dt)
    except Exception:
        close = None
    number = number_service.number_from_close(game_key, close) if close else None
    return {"close_price": str(close) if close is not None else None, "result_number": number}


@router.get("/manual-result/{game_id}", response_model=APIResponse[dict])
async def get_manual_result(game_id: str, _: SuperAdmin, day: str | None = None):
    from app.models.games.bets import GameManualResult, GameResult
    from app.services.games.common import ist_day

    key = ids.settings_key(game_id)
    if key is None or key not in _NUMBER_GAMES:
        raise HTTPException(status_code=404, detail="Manual result is only for number games")
    s = await GameSettings.load_singleton()
    cfg = s.games.get(key) or GameConfig()
    d = day or ist_day()

    mr = await GameManualResult.find_one(
        GameManualResult.game_key == key, GameManualResult.day == d
    )
    declared = await GameResult.find_one(
        GameResult.game_key == key, GameResult.day == d,
        GameResult.window_number == None,  # noqa: E711
    )
    return APIResponse(
        data={
            "game": key,
            "day": d,
            "auto_result": bool(cfg.auto_result),
            "result_time": cfg.result_time,
            "manual": (
                {
                    "result_number": mr.result_number,
                    "close_price": str(mr.close_price) if mr.close_price is not None else None,
                    "set_at": mr.updated_at.isoformat() if getattr(mr, "updated_at", None) else None,
                }
                if mr
                else None
            ),
            "auto_preview": await _auto_preview(key, cfg),
            "declared": (
                {
                    "result_number": declared.result_number,
                    "close_price": str(declared.close_price),
                    "source": declared.price_source,
                }
                if declared
                else None
            ),
        }
    )


@router.put("/manual-result/{game_id}", response_model=APIResponse[dict])
async def set_manual_result(game_id: str, payload: dict, admin: SuperAdmin):
    from app.models.games.bets import GameManualResult, GameResult
    from app.services.games import number_service
    from app.services.games.common import ist_day
    from app.utils.decimal_utils import quantize_money, to_decimal, to_decimal128

    key = ids.settings_key(game_id)
    if key is None or key not in _NUMBER_GAMES:
        raise HTTPException(status_code=404, detail="Manual result is only for number games")
    d = str(payload.get("day") or ist_day())

    # Refuse to change a result the settler has ALREADY published — that would
    # desync the users who saw it (and re-paying settled bets is out of scope).
    already = await GameResult.find_one(
        GameResult.game_key == key, GameResult.day == d,
        GameResult.window_number == None,  # noqa: E711
    )
    if already is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Result for {d} is already declared (#{already.result_number}) — it can't be changed.",
        )

    # Accept a closing price (primary) and/or a two-digit number. If a price is
    # given, DERIVE the number from it so the two always agree.
    close_raw = payload.get("close_price")
    num_raw = payload.get("result_number")
    close_dec = None
    number: int | None = None
    if close_raw not in (None, ""):
        close_dec = quantize_money(to_decimal(close_raw))
        number = number_service.number_from_close(key, close_dec)
    elif num_raw not in (None, ""):
        number = int(num_raw) % 100
    if number is None:
        raise HTTPException(status_code=422, detail="Provide a closing price or a winning number")

    mr = await GameManualResult.find_one(
        GameManualResult.game_key == key, GameManualResult.day == d
    )
    if mr is None:
        mr = GameManualResult(
            game_key=key, day=d, result_number=number,
            close_price=to_decimal128(close_dec) if close_dec is not None else None,
            set_by=admin.id,
        )
        await mr.insert()
    else:
        mr.result_number = number
        mr.close_price = to_decimal128(close_dec) if close_dec is not None else None
        mr.set_by = admin.id
        await mr.save()

    # If it's already past result_time today, publish immediately instead of
    # waiting for the 30 s settlement tick.
    settled = 0
    s = await GameSettings.load_singleton()
    cfg = s.games.get(key) or GameConfig()
    if d == ist_day() and not cfg.auto_result:
        try:
            settled = await number_service.declare_and_settle(key)
        except Exception:
            settled = 0

    return APIResponse(
        data={"game": key, "day": d, "result_number": number,
              "close_price": str(close_dec) if close_dec is not None else None,
              "settled_now": settled},
        message="Manual result saved",
    )


@router.delete("/manual-result/{game_id}", response_model=APIResponse[dict])
async def clear_manual_result(game_id: str, _: SuperAdmin, day: str | None = None):
    from app.models.games.bets import GameManualResult, GameResult
    from app.services.games.common import ist_day

    key = ids.settings_key(game_id)
    if key is None or key not in _NUMBER_GAMES:
        raise HTTPException(status_code=404, detail="Manual result is only for number games")
    d = day or ist_day()
    declared = await GameResult.find_one(
        GameResult.game_key == key, GameResult.day == d,
        GameResult.window_number == None,  # noqa: E711
    )
    if declared is not None:
        raise HTTPException(status_code=409, detail="Already declared — can't clear.")
    mr = await GameManualResult.find_one(
        GameManualResult.game_key == key, GameManualResult.day == d
    )
    if mr is not None:
        await mr.delete()
    return APIResponse(data={"game": key, "day": d, "cleared": True})


# ── Games → main withdrawal approvals ────────────────────────────────
@router.get("/withdrawals", response_model=APIResponse[list])
async def list_withdrawals(_: SuperAdmin, status: str = "PENDING"):
    q = {}
    if status:
        q["status"] = status
    rows = await GamesWithdrawalRequest.find(q).sort("-created_at").limit(200).to_list()
    return APIResponse(
        data=[
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                "amount": str(r.amount),
                "status": r.status.value,
                "user_remark": r.user_remark,
                "admin_remark": r.admin_remark,
                "created_at": r.created_at,
                "processed_at": r.processed_at,
            }
            for r in rows
        ]
    )


@router.post("/withdrawals/{request_id}/approve", response_model=APIResponse[dict])
async def approve_withdrawal(request_id: str, admin: SuperAdmin, payload: dict | None = None):
    res = await wallet_service.approve_games_withdrawal(
        PydanticObjectId(request_id), admin.id, (payload or {}).get("admin_remark")
    )
    return APIResponse(data=res, message="Approved")


@router.post("/withdrawals/{request_id}/reject", response_model=APIResponse[dict])
async def reject_withdrawal(request_id: str, admin: SuperAdmin, payload: dict | None = None):
    res = await wallet_service.reject_games_withdrawal(
        PydanticObjectId(request_id), admin.id, (payload or {}).get("reason")
    )
    return APIResponse(data=res, message="Rejected")


# ── Hierarchy commission (temporary wallet) — view + release ─────────
@router.get("/hierarchy-earnings", response_model=APIResponse[list])
async def hierarchy_earnings(_: SuperAdmin):
    """Admins/brokers with held games commission (temporary wallet > 0)."""
    from app.models.user import User
    from app.models.wallet import Wallet

    wallets = await Wallet.find(
        {"$expr": {"$gt": [{"$toDecimal": "$temporary_balance"}, 0]}}
    ).to_list()
    out = []
    for w in wallets:
        u = await User.get(w.user_id)
        if u is None:
            continue
        out.append({
            "user_id": str(w.user_id),
            "user_code": u.user_code,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "temporary_balance": str(w.temporary_balance),
            "temporary_total_earned": str(w.temporary_total_earned),
            "temporary_total_released": str(w.temporary_total_released),
        })
    return APIResponse(data=out)


@router.post("/hierarchy-earnings/{user_id}/release", response_model=APIResponse[dict])
async def release_hierarchy_earnings(user_id: str, admin: SuperAdmin, payload: dict):
    amount = payload.get("amount")
    res = await wallet_service.release_temp_to_main(
        PydanticObjectId(user_id), amount, actor_id=admin.id
    )
    return APIResponse(data=res, message="Released to main wallet")


# ── Manual game entry + reversal (SUPER_ADMIN) ────────────────────────
# One typed NIFTY close drives all 3 nifty games (Number/Jackpot/Bracket).
@router.get("/manual-entry", response_model=APIResponse[dict])
async def manual_entry_preview(_: SuperAdmin, day: str | None = None):
    from app.services.games import manual_game_service as mgs
    from app.utils.time_utils import now_ist

    d = day or now_ist().strftime("%Y-%m-%d")
    return APIResponse(data=await mgs.preview_day(d))


@router.post("/manual-entry/declare", response_model=APIResponse[dict])
async def manual_entry_declare(payload: dict, _: SuperAdmin):
    from app.services.games import manual_game_service as mgs
    from app.utils.time_utils import now_ist

    d = str(payload.get("day") or now_ist().strftime("%Y-%m-%d"))
    close = payload.get("close_price")
    if close in (None, ""):
        raise HTTPException(status_code=400, detail="close_price is required")
    try:
        res = await mgs.declare_day(d, close)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(data=res, message="Result declared for all 3 games.")


@router.post("/manual-entry/reverse", response_model=APIResponse[dict])
async def manual_entry_reverse(payload: dict, _: SuperAdmin):
    from app.services.games import manual_game_service as mgs
    from app.utils.time_utils import now_ist

    d = str(payload.get("day") or now_ist().strftime("%Y-%m-%d"))
    res = await mgs.reverse_day(d)
    return APIResponse(
        data=res, message="Reversed — payouts clawed back, results cleared. Re-declare with the correct close."
    )


@router.post("/manual-entry/declare-game", response_model=APIResponse[dict])
async def manual_entry_declare_game(payload: dict, _: SuperAdmin):
    """Declare/settle ONE nifty game from a typed close (per-game control)."""
    from app.services.games import manual_game_service as mgs
    from app.utils.time_utils import now_ist

    d = str(payload.get("day") or now_ist().strftime("%Y-%m-%d"))
    game_key = str(payload.get("game_key") or "")
    close = payload.get("close_price")
    if close in (None, ""):
        raise HTTPException(status_code=400, detail="close_price is required")
    try:
        res = await mgs.declare_game(d, game_key, close)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(data=res, message=f"{game_key} declared.")


@router.post("/manual-entry/reverse-game", response_model=APIResponse[dict])
async def manual_entry_reverse_game(payload: dict, _: SuperAdmin):
    """Reverse ONE nifty game so it can be re-declared without touching the others."""
    from app.services.games import manual_game_service as mgs
    from app.utils.time_utils import now_ist

    d = str(payload.get("day") or now_ist().strftime("%Y-%m-%d"))
    game_key = str(payload.get("game_key") or "")
    try:
        res = await mgs.reverse_game(game_key, d)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse(data=res, message=f"{game_key} reversed — re-declare the correct close.")
