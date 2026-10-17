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
    from app.services.games.common import nse_closed_on
    from app.utils.time_utils import now_ist

    cached = {
        **cached,
        "hierarchyDeniedGameKeys": [],
        "nse_open_today": not await nse_closed_on(now_ist().date()),
    }
    return APIResponse(data=cached)
