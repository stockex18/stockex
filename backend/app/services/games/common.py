"""Small shared helpers for the games subsystem — IST day/time + window math.

All games are IST-scoped (Asia/Kolkata). These helpers centralize the day
string and window-number computation so services and settlement agree.
"""

from __future__ import annotations

from datetime import datetime, time

from app.utils.time_utils import IST, now_ist

# ── NSE session for the NIFTY games ────────────────────────────────────
# NIFTY games follow the NSE calendar. A normal trading day is the regular
# session; a weekend or full-day holiday has none; and a SPECIAL session (Diwali
# Muhurat, a short weekday session — a calendar row with its own open/close
# times) is that day's only session, weekend or not. Trading has honoured
# special sessions for a while (`holiday_service.special_session`); the games
# did not, so on the 8 Nov 2026 Muhurat (Sunday 14:20-15:30) every NIFTY game
# stayed "closed". On such a day each NIFTY game now runs inside the session,
# its times re-based on it (see `rebase_config`). Added at the operator's
# request.

_START_FIELDS = ("start_time", "bidding_start_time")
_END_FIELDS = ("end_time", "bidding_end_time", "max_bid_time", "result_time")


def is_nifty_game(game_key: str | None) -> bool:
    return str(game_key or "").lower().startswith("nifty")


async def nse_special_session_for_games(d) -> tuple[time, time] | None:
    """The special NSE session on `d` (Muhurat, a short weekday session) that
    the NIFTY games follow, or None on a normal day / a day with no session."""
    from app.services import holiday_service

    return await holiday_service.special_session("NSE", d)


async def nse_closed_on(d) -> bool:
    """No NSE session for the NIFTY games on `d`: a weekend or full-day
    holiday WITHOUT a special session. A special session opens the day."""
    from app.services import holiday_service
    from app.utils.time_utils import is_weekend

    if await nse_special_session_for_games(d) is not None:
        return False
    return is_weekend(d) or await holiday_service.is_market_holiday("NSE", d)


async def nifty_market_open(at: datetime | None = None) -> bool:
    """Is NIFTY trading right now, for the games' price logic? Inside the
    special session on a special-session day; otherwise the regular weekday
    hours check the games always used (`is_market_open`)."""
    from app.utils.time_utils import is_market_open, to_ist

    now = to_ist(at or now_ist())
    ss = await nse_special_session_for_games(now.date())
    if ss is not None:
        return ss[0] <= now.time() <= ss[1]
    return is_market_open(now)


def _secs(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _hms(sec: int) -> str:
    sec = max(0, min(86399, sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def rebase_config(cfg, session: tuple[time, time]):
    """A copy of a NIFTY game's config with its times moved into `session`.

    Each time keeps its distance from the regular session it belongs to:
    start-type times (start, bidding start) from the OPEN, end-type times
    (end, bidding end, max bid, result) from the CLOSE. With the regular
    session 09:15-15:30 and a 14:20-15:30 Muhurat: start 09:15 -> 14:20,
    bidding end 15:00 (30 min before close) -> 15:00, result 15:45 (15 min
    after close) -> 15:45. A start can't move before the session opens. If a
    game's window ends up empty (end <= start) it simply never opens that day.
    """
    from app.utils.time_utils import market_close_time, market_open_time

    reg_open, reg_close = _secs(market_open_time()), _secs(market_close_time())
    ses_open, ses_close = _secs(session[0]), _secs(session[1])
    update: dict[str, str] = {}
    for f in _START_FIELDS:
        v = getattr(cfg, f, None)
        if v:
            update[f] = _hms(max(ses_open, ses_open + _secs(parse_hms(v)) - reg_open))
    for f in _END_FIELDS:
        v = getattr(cfg, f, None)
        if v:
            update[f] = _hms(ses_close + _secs(parse_hms(v)) - reg_close)
    return cfg.model_copy(update=update)


async def effective_config(settings, game_key: str, d):
    """`game_key`'s config for day `d`: re-based onto the special NSE session
    when `d` has one (NIFTY games only), otherwise unchanged. Use it wherever
    a game reads its times — for settlement, with the BET's day, not today."""
    cfg = settings.games.get(game_key) if settings is not None else None
    if cfg is None or not is_nifty_game(game_key):
        return cfg
    if isinstance(d, str):
        from datetime import date as _date

        d = _date.fromisoformat(d)
    ss = await nse_special_session_for_games(d)
    return rebase_config(cfg, ss) if ss is not None else cfg


async def assert_nse_open_today(game_key: str, now: datetime) -> None:
    """NIFTY games follow the NSE calendar. On a Saturday the clock alone said
    "open": a window ran, bets went in on a frozen price, and every round
    could only end in a refund. BTC games run 24x7 and are not touched.
    A special session (Muhurat) counts as open — see above."""
    from app.core.exceptions import GameWindowClosedError

    if is_nifty_game(game_key) and await nse_closed_on(now.date()):
        raise GameWindowClosedError("NIFTY market is closed today — games open on the next trading day")


def ist_datetime_for_day(day: str) -> datetime:
    """IST-midnight datetime for a 'YYYY-MM-DD' day string."""
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, tzinfo=IST)


def ist_day(dt: datetime | None = None) -> str:
    """IST day string 'YYYY-MM-DD' for the given (or current) moment."""
    d = dt if dt is not None else now_ist()
    return d.strftime("%Y-%m-%d")


def parse_hms(s: str) -> time:
    """Parse 'HH:MM' or 'HH:MM:SS' into a time (IST)."""
    parts = [int(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.append(0)
    h, m, sec = parts[0], parts[1], parts[2]
    return time(hour=h, minute=m, second=sec)


def seconds_since_ist_midnight(dt: datetime | None = None) -> int:
    d = dt if dt is not None else now_ist()
    return d.hour * 3600 + d.minute * 60 + d.second


def window_number_for(
    now: datetime, start_hms: str, round_duration_sec: int
) -> int:
    """1-based window index since `start_hms` for a fixed round duration.

    Window 1 covers [start, start+dur), window 2 [start+dur, start+2·dur), …
    Values <= 0 (before session start) clamp to 0.
    """
    start = parse_hms(start_hms)
    start_sec = start.hour * 3600 + start.minute * 60 + start.second
    now_sec = now.hour * 3600 + now.minute * 60 + now.second
    if round_duration_sec <= 0:
        return 0
    delta = now_sec - start_sec
    if delta < 0:
        return 0
    return delta // round_duration_sec + 1


def window_open_close_ist(
    day_ist: datetime, start_hms: str, round_duration_sec: int, window_number: int
) -> tuple[datetime, datetime]:
    """Return (open_dt, close_dt) IST for a given 1-based window number."""
    start = parse_hms(start_hms)
    base = day_ist.replace(
        hour=start.hour, minute=start.minute, second=start.second, microsecond=0
    )
    from datetime import timedelta

    open_dt = base + timedelta(seconds=round_duration_sec * (window_number - 1))
    close_dt = open_dt + timedelta(seconds=round_duration_sec)
    return open_dt, close_dt
