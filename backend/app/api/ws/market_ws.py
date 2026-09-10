"""Market data WebSocket — clients subscribe to instrument tokens, receive
LTP / depth ticks pushed from the mock feed (or future external feed).

Protocol (JSON messages over a single WS):
    Client → Server:
        {"type":"subscribe","tokens":["..."] }
        {"type":"unsubscribe","tokens":["..."] }
        {"type":"ping"}
    Server → Client:
        {"type":"tick","payload":{...quote...}}
        {"type":"pong"}
        {"type":"error","message":"..."}

Auth (optional): pass ``?token=<user_jwt>`` to enable per-user spread
overrides set by the admin on that user's account. Anonymous connections
still receive the global admin segment-level spread.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.ws._helpers import is_connected, safe_send_text
from app.core.config import settings
from app.core.ws_hub import market_tick_hub
from app.core.ws_limiter import acquire as ws_limit_acquire
from app.core.ws_limiter import client_ip as ws_client_ip
from app.core.ws_limiter import release as ws_limit_release
from app.services import market_data_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Per-user spread helpers ─────────────────────────────────────────────

async def _resolve_user_id(token: str | None) -> str | None:
    """Decode an optional JWT and return the ``sub`` (user_id).
    Returns ``None`` on any failure so the caller degrades gracefully."""
    if not token:
        return None
    try:
        from app.core.security import decode_token
        payload = decode_token(token, expected_type="access")
        uid = payload.get("sub")
        return str(uid) if uid else None
    except Exception:
        return None


async def _load_spread_meta(user_id: str | None) -> dict[str, Any] | None:
    """Load a user's per-segment spread overrides from DB.

    Returns ``None`` for anonymous sessions (no per-user spread). For
    authenticated users returns a meta dict with structure::

        {
            "spreads": {segment_name: {"pips": float, "type": str}},
            "token_segments": {},   # populated lazily at subscribe time
        }

    Only segments that have ``spreadPips > 0`` are included so the
    ``_frame_for_ws`` hot-path never does useless work.
    """
    if not user_id:
        return None
    meta: dict[str, Any] = {"spreads": {}, "token_segments": {}}
    try:
        from beanie import PydanticObjectId
        from app.models.netting import UserSegmentOverride
        uid = PydanticObjectId(user_id)
        overrides = await UserSegmentOverride.find(
            UserSegmentOverride.user_id == uid
        ).to_list()
        for o in overrides:
            pips = getattr(o, "spreadPips", None)
            stype = getattr(o, "spreadType", None)
            if pips is not None and float(pips) > 0:
                meta["spreads"][o.segment_name] = {
                    "pips": float(pips),
                    "type": str(stype or "fixed"),
                }
    except Exception:
        logger.debug("spread_meta_load_failed uid=%s", user_id, exc_info=True)
    return meta


async def _register_token_segment(tok: str, meta: dict[str, Any]) -> None:
    """Populate ``meta["token_segments"][tok]`` with the admin-row segment
    name so ``_frame_for_ws`` can match it against the user's spread map.
    Skips tokens already registered. Results are Redis-cached upstream."""
    if tok in meta.get("token_segments", {}):
        return
    try:
        seg_info = await market_data_service.get_segment_for_token(tok)
        if seg_info:
            from app.services.netting_service import _SEGMENT_NAME_MAP
            seg_type, _sym = seg_info
            admin_row = _SEGMENT_NAME_MAP.get(seg_type, seg_type)
            meta.setdefault("token_segments", {})[tok] = admin_row
    except Exception:
        logger.debug("token_segment_lookup_failed token=%s", tok, exc_info=True)


def _apply_user_spread(quotes: list[dict], meta: dict[str, Any] | None) -> list[dict]:
    """Apply per-user spread to a list of quote dicts (snapshot / pump
    frames that bypass the hub's ``_frame_for_ws`` path). Returns a new
    list with per-user adjusted bid/ask where applicable."""
    if not meta:
        return quotes
    spreads = meta.get("spreads") or {}
    token_segments = meta.get("token_segments") or {}
    if not spreads or not token_segments:
        return quotes
    out: list[dict] = []
    for q in quotes:
        tok = str(q.get("token", ""))
        segment = token_segments.get(tok)
        spread_cfg = spreads.get(segment) if segment else None
        if not spread_cfg:
            out.append(q)
            continue
        pips = float(spread_cfg.get("pips") or 0)
        ltp = float(q.get("ltp") or 0)
        if pips <= 0 or ltp <= 0:
            out.append(q)
            continue
        half = pips / 2.0
        mode = str(spread_cfg.get("type") or "fixed").lower()
        tick = dict(q)
        if mode == "fixed":
            tick["bid"] = round(ltp - half, 8)
            tick["ask"] = round(ltp + half, 8)
        else:
            live_bid = float(q.get("bid") or 0)
            live_ask = float(q.get("ask") or 0)
            live_spread = (
                (live_ask - live_bid) if (live_bid > 0 and live_ask > 0) else 0.0
            )
            if live_spread < pips:
                tick["bid"] = round(ltp - half, 8)
                tick["ask"] = round(ltp + half, 8)
        out.append(tick)
    return out


# ── WebSocket endpoint ──────────────────────────────────────────────────

@router.websocket("/ws/marketdata")
async def market_ws(
    ws: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Per-client market-data socket.

    Internal change: realtime ticks now arrive via the process-wide
    ``MarketTickHub`` (one shared Redis pub/sub for the whole worker)
    instead of opening a dedicated pub/sub connection per client. The
    hub maintains an in-memory ``token -> set[WebSocket]`` map and
    fans each tick out to every subscribed socket.

    The wire-level WebSocket protocol the client speaks (subscribe /
    unsubscribe / ping / snapshot / tick frames, message shapes,
    ordering) is completely unchanged — only the routing inside the
    server is consolidated. Both the initial subscribe-time snapshot
    and the 5 s heartbeat-snapshot pump are preserved exactly.

    Per-user spread: pass ``?token=<jwt>`` to receive bid/ask prices
    adjusted to the spread the admin configured for this user's account
    (``UserSegmentOverride.spreadPips``). Without a token (or when no
    override exists) the connection receives the global admin spread.
    """
    # Per-IP rate limit — reject before accept() so a flooding client
    # doesn't even get a connection slot. Code 4429 mirrors HTTP 429.
    ip = ws_client_ip(ws)
    if not await ws_limit_acquire(ip, max_per_ip=settings.WS_MAX_CONNECTIONS_PER_IP):
        await ws.close(code=4429)
        return

    await ws.accept()
    subscribed: set[str] = set()
    pump_task: asyncio.Task | None = None

    # Resolve user identity and load per-user spread overrides.
    # meta is None for anonymous connections (no extra work done per tick).
    user_id = await _resolve_user_id(token)
    meta = await _load_spread_meta(user_id)
    if meta:
        market_tick_hub.attach_meta(ws, meta)

    async def pump():
        # 5 s heartbeat snapshot. The hub carries the realtime path;
        # this just guarantees eventual consistency if a publish ever
        # gets dropped (Redis reconnect, pool exhaustion, etc.) — the
        # client's stored LTP never drifts more than 5 s from reality
        # even in worst case.
        try:
            while True:
                await asyncio.sleep(5)
                if not is_connected(ws):
                    return
                if not subscribed:
                    continue
                tokens_now = list(subscribed)
                results = await asyncio.gather(
                    *(market_data_service.get_display_quote(t) for t in tokens_now),
                    return_exceptions=True,
                )
                snapshots = _apply_user_spread(
                    [r for r in results if isinstance(r, dict)], meta
                )
                if snapshots:
                    if not await safe_send_text(
                        ws,
                        json.dumps({"type": "tick", "payload": snapshots}, default=str),
                    ):
                        return
        except (WebSocketDisconnect, asyncio.CancelledError):
            return
        except Exception as e:  # pragma: no cover
            logger.exception("market_ws_pump_failed", extra={"error": str(e)})

    try:
        # Hub is started eagerly in the FastAPI lifespan. ``start()``
        # is idempotent so a stray race here is still safe.
        await market_tick_hub.start()

        await safe_send_text(
            ws, json.dumps({"type": "hello", "message": "market_ws_connected"})
        )
        pump_task = asyncio.create_task(pump())

        while True:
            data = await ws.receive_text()
            try:
                msg: dict[str, Any] = json.loads(data)
            except json.JSONDecodeError:
                await safe_send_text(
                    ws, json.dumps({"type": "error", "message": "invalid_json"})
                )
                continue

            t = msg.get("type")
            if t == "subscribe":
                tokens = [str(x) for x in (msg.get("tokens") or []) if x]
                # Newly-requested tokens go into both the hub (so ticks
                # start flowing immediately) and the upstream feed
                # ref-count (so the underlying provider keeps pulling
                # them). Already-subscribed tokens are skipped to keep
                # the hub map free of duplicate add() noise.
                new_tokens = [tok for tok in tokens if tok not in subscribed]
                # Per-connection subscription cap — refuse the whole
                # batch when accepting it would push the socket past
                # `WS_MAX_SUBSCRIPTIONS_PER_CONN`. Partial-accept would
                # leave the client wondering which symbols streamed and
                # which silently dropped; a clean reject + explicit
                # `subscription_limit` error frame lets the frontend
                # toast the user with an actionable "unsubscribe
                # something first" message. Already-subscribed tokens
                # in the batch are free — they don't count against the
                # quota.
                cap = settings.WS_MAX_SUBSCRIPTIONS_PER_CONN
                if cap > 0 and len(subscribed) + len(new_tokens) > cap:
                    await safe_send_text(
                        ws,
                        json.dumps({
                            "type": "error",
                            "code": "subscription_limit",
                            "limit": cap,
                            "current": len(subscribed),
                            "attempted": len(new_tokens),
                            "message": (
                                f"Subscription limit reached "
                                f"({len(subscribed)}/{cap} active). "
                                f"Unsubscribe some symbols before adding new ones."
                            ),
                        }),
                    )
                    continue
                subscribed.update(tokens)
                for tok in new_tokens:
                    market_tick_hub.add(tok, ws)
                    # Populate token → admin-segment mapping in meta so
                    # _frame_for_ws (and _apply_user_spread for snapshots)
                    # can find the right spread override per tick.
                    if meta:
                        await _register_token_segment(tok, meta)
                if new_tokens:
                    market_data_service.subscribe(new_tokens)
                # Initial snapshots — parallel fetch so a freshly-typed
                # search ("G" → 80 results) doesn't block the client for
                # the sum of every quote's overlay latency. Failed quotes
                # are silently dropped so one slow Zerodha REST call
                # can't delay the whole batch. After this, the hub
                # streams every subsequent tick in realtime.
                if tokens:
                    results = await asyncio.gather(
                        *(market_data_service.get_display_quote(tok) for tok in tokens),
                        return_exceptions=True,
                    )
                    snaps = _apply_user_spread(
                        [r for r in results if isinstance(r, dict)], meta
                    )
                else:
                    snaps = []
                await safe_send_text(
                    ws,
                    json.dumps({"type": "snapshot", "payload": snaps}, default=str),
                )
            elif t == "unsubscribe":
                tokens = [str(x) for x in (msg.get("tokens") or []) if x]
                gone = [tok for tok in tokens if tok in subscribed]
                subscribed.difference_update(tokens)
                for tok in gone:
                    market_tick_hub.remove(tok, ws)
                if gone:
                    market_data_service.unsubscribe(gone)
            elif t == "ping":
                await safe_send_text(ws, json.dumps({"type": "pong"}))
            else:
                await safe_send_text(
                    ws, json.dumps({"type": "error", "message": "unknown_type"})
                )

    except WebSocketDisconnect:
        pass
    except RuntimeError as e:
        # Starlette raises a bare RuntimeError ("WebSocket is not connected.
        # Need to call accept first.") when the client vanished between our
        # receive_text() and the socket teardown — an abrupt disconnect that
        # didn't surface as a clean WebSocketDisconnect frame (browser tab
        # closed, network drop, app backgrounded). With 140+ live sockets this
        # churns constantly; logging it as ERROR + full traceback spammed the
        # logs and inflated the error count for no real fault. Treat a
        # "not connected" / "disconnect" RuntimeError as an ordinary close,
        # but RE-RAISE anything else so genuine RuntimeErrors still surface.
        _msg = str(e).lower()
        if "not connected" not in _msg and "disconnect" not in _msg:
            logger.exception("market_ws_main_failed")
    except Exception:  # pragma: no cover
        logger.exception("market_ws_main_failed")
    finally:
        if pump_task is not None:
            pump_task.cancel()
            try:
                await pump_task
            except (asyncio.CancelledError, Exception):  # pragma: no cover
                pass
        # Detach per-user spread meta so the hub's _ws_meta map doesn't leak.
        market_tick_hub.detach_meta(ws)
        # Detach from every token we registered so the hub's subscriber
        # map doesn't leak. Targeted ``remove()`` per token keeps this
        # O(K_per_client) instead of scanning every token the hub knows
        # about — important under disconnect storms with thousands of
        # tokens platform-wide.
        for tok in list(subscribed):
            try:
                market_tick_hub.remove(tok, ws)
            except Exception:  # pragma: no cover
                pass
        # Tell the upstream feed we no longer need these tokens.
        if subscribed:
            try:
                market_data_service.unsubscribe(list(subscribed))
            except Exception:  # pragma: no cover
                pass
        # Release per-IP connection slot.
        try:
            await ws_limit_release(ip)
        except Exception:  # pragma: no cover
            pass
