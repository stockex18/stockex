"""Today is not a result until the game says it is.

Reported twice, as two symptoms of one bug. At 10:42 IST the strip already
read "2026-09-01 SESSION CLOSE 24,068.90" for a session that had hours left to
run, and the number did not match the real close.

Both come from the same place. The results strip reads Kite's DAILY candles so
a quiet day still shows an outcome — but the candle for the CURRENT session
exists from the opening bell and keeps moving all day. Taking it as a close
published today's row early, with a price that was simply wherever NIFTY
happened to be at the moment of the read.

Today now appears only once the game has actually settled it.
"""

from __future__ import annotations

import inspect

import pytest

from app.api.v1.user.games import bracket

TODAY = "2026-09-01"
SESSIONS = [(TODAY, "24068.90"), ("2026-08-31", "24080.40"), ("2026-08-28", "24175.65")]


def _strip(settled: dict) -> list:
    """The filter as the endpoint applies it."""
    return [
        (d, settled.get(d, c)) for d, c in SESSIONS if d != TODAY or d in settled
    ]


# -- the reported case -------------------------------------------------
def test_an_unsettled_today_is_not_shown():
    """The session is still running; there is no result to report yet."""
    days = [d for d, _ in _strip({})]
    assert TODAY not in days
    assert days == ["2026-08-31", "2026-08-28"]


def test_the_latest_row_is_the_last_CLOSED_session():
    """The card at the top reads `sessionResults[0]`, so this is what it shows."""
    assert _strip({})[0][0] == "2026-08-31"


def test_today_appears_the_moment_the_game_settles_it():
    out = _strip({TODAY: "24055.80"})
    assert out[0] == (TODAY, "24055.80")


def test_a_settled_today_shows_the_DECLARED_price_not_the_candle():
    """The bracket settles on the last 1-minute close, which can differ from
    the daily candle by a tick. Players were paid on the declared number."""
    assert _strip({TODAY: "24055.80"})[0][1] == "24055.80"
    assert _strip({TODAY: "24055.80"})[0][1] != "24068.90"


def test_earlier_sessions_are_untouched():
    """They are genuine closes and never needed the game's permission."""
    out = _strip({})
    assert ("2026-08-31", "24080.40") in out
    assert ("2026-08-28", "24175.65") in out


# -- wiring ------------------------------------------------------------
def test_the_endpoint_filters_on_todays_ist_date():
    src = inspect.getsource(bracket.recent_results)
    assert 'now_ist().strftime("%Y-%m-%d")' in src
    assert "if d != _today or d in settled" in src


def test_an_extra_session_is_pulled_to_cover_the_dropped_one():
    """Dropping today would otherwise leave the strip one row short, and the
    oldest row without a previous close to take its direction from."""
    src = inspect.getsource(bracket.recent_results)
    assert "recent_nifty_session_closes(n + 2)" in src


def test_the_settled_result_still_wins_where_there_is_one():
    src = inspect.getsource(bracket.recent_results)
    assert "settled.get(d, str(c))" in src


def test_the_dead_feed_fallback_survives():
    """With no candles at all, settled days are still worth showing."""
    src = inspect.getsource(bracket.recent_results)
    assert "sorted(settled, reverse=True)" in src
