"""User games settings — read-only view (short Redis cache for the 3s poll)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUser
from app.core.redis_client import cache_get, cache_set
from app.models.games.settings import GameSettings
from app.schemas.common import APIResponse

router = APIRouter(tags=["user-games-settings"])

_CACHE_KEY = "games:settings:public:v1"
_CACHE_TTL = 3  # seconds — matches the client 3s poll cadence


@router.get("/settings", response_model=APIResponse[dict])
async def get_settings(user: CurrentUser):
    cached = await cache_get(_CACHE_KEY)
    if cached is None:
        s = await GameSettings.load_singleton()
        cached = {
            "games_enabled": s.games_enabled,
            "maintenance_mode": s.maintenance_mode,
            "maintenance_message": s.maintenance_message,
            "token_value": s.token_value,
            "games": {k: v.model_dump(mode="json") for k, v in s.games.items()},
        }
        await cache_set(_CACHE_KEY, cached, ttl_sec=_CACHE_TTL)
    # Per-user hierarchy game denial is deferred (v1 has none).
    # `nse_open_today`: false on a weekend / NSE holiday — the NIFTY games show
    # "market closed" instead of a running window (the server refuses bets too).
    # On a special NSE session (Diwali Muhurat) it is TRUE and the NIFTY games'
    # times below are that day's, re-based onto the session, so the screens show
    # the right windows and countdowns. `nse_special_session` carries the
    # session's times for a banner (null on a normal day).
    from app.models.games.settings import GameConfig
    from app.services.games.common import (
        is_nifty_game,
        nse_closed_on,
        nse_special_session_for_games,
        rebase_config,
    )
    from app.utils.time_utils import now_ist

    today = now_ist().date()
    session = await nse_special_session_for_games(today)
    games = cached.get("games") or {}
    if session is not None:
        games = {
            k: (rebase_config(GameConfig(**v), session, k).model_dump(mode="json") if is_nifty_game(k) else v)
            for k, v in games.items()
        }
    cached = {
        **cached,
        "games": games,
        "hierarchyDeniedGameKeys": [],
        "nse_open_today": not await nse_closed_on(today),
        "nse_special_session": (
            {"open": session[0].strftime("%H:%M"), "close": session[1].strftime("%H:%M")}
            if session is not None
            else None
        ),
    }
    return APIResponse(data=cached)
