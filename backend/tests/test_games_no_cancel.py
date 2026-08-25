"""Games: a live bet can be CHANGED but never withdrawn.

Jackpot always worked this way; Up/Down and Number let a player pull a bet and
take the stake back. Operator rule: modification is allowed, cancellation is
not — in every game.

The system-side refund in `settlement_engine.cancel_stale_nifty_bets` is a
different thing entirely (the house returning money it could not settle) and
must survive.
"""

from __future__ import annotations

import inspect

import pytest

from app.api.v1.user.games import bracket, jackpot, number, updown


def _routes(mod):
    out = []
    for r in mod.router.routes:
        for m in getattr(r, "methods", set()) or set():
            out.append((m, r.path))
    return out


ALL_GAMES = [("updown", updown), ("number", number), ("jackpot", jackpot), ("bracket", bracket)]


@pytest.mark.parametrize("name,mod", ALL_GAMES)
def test_no_game_exposes_a_cancel_route(name, mod):
    """A DELETE on a bet is the only way a player could withdraw one."""
    assert not [r for r in _routes(mod) if r[0] == "DELETE"], name


@pytest.mark.parametrize("name,mod", [("updown", updown), ("number", number), ("jackpot", jackpot)])
def test_modification_is_still_offered(name, mod):
    """Removing cancel must not take editing with it — that is the half the
    operator wants kept."""
    assert [r for r in _routes(mod) if r[0] == "PATCH"], name


@pytest.mark.parametrize("mod_name", [
    "app.services.games.updown_service",
    "app.services.games.number_service",
])
def test_the_service_function_is_gone_too(mod_name):
    """A route can be re-added by accident; a missing function cannot be
    called by one."""
    import importlib

    assert not hasattr(importlib.import_module(mod_name), "cancel_bet")


def test_the_house_can_still_refund_what_it_cannot_settle():
    """Not a player action — this one stays."""
    from app.services.games import settlement_engine

    assert hasattr(settlement_engine, "cancel_stale_nifty_bets")
    assert "CANCELLED" in inspect.getsource(settlement_engine.cancel_stale_nifty_bets)


# -- the bracket results strip ----------------------------------------
def test_bracket_results_come_from_sessions_not_from_play():
    """Built from settled trades, a quiet day showed nothing and a new game
    showed almost nothing — which is what happened: two trades, both today,
    so "last 5 days" had one row."""
    src = inspect.getsource(bracket.recent_results)
    assert "recent_nifty_session_closes" in src


def test_a_traded_day_still_shows_what_players_were_settled_on():
    """The bracket settles on the last 1-minute candle, which can differ by a
    tick from the daily candle — the declared number must win."""
    src = inspect.getsource(bracket.recent_results)
    assert "settled.get(d, str(c))" in src


def test_one_extra_session_is_pulled_for_the_direction():
    """Otherwise the oldest row has no previous close and loses its arrow."""
    src = inspect.getsource(bracket.recent_results)
    assert "recent_nifty_session_closes(n + 1)" in src


def test_a_dead_feed_falls_back_instead_of_showing_nothing():
    src = inspect.getsource(bracket.recent_results)
    assert "if sessions:" in src and "sorted(settled, reverse=True)" in src


def test_the_session_reader_never_invents_a_close():
    from app.services.games import price_resolver

    src = inspect.getsource(price_resolver.recent_nifty_session_closes)
    assert "return []" in src
    assert "if close <= 0:" in src


def test_the_session_day_comes_from_the_epoch_kite_actually_sends():
    """Kite's candles carry `time` (a unix epoch), not a `date` object. Reading
    `date` gave every session the day "None", which collapsed five sessions
    into one row."""
    from app.services.games import price_resolver

    src = inspect.getsource(price_resolver.recent_nifty_session_closes)
    assert 'c.get("time")' in src
    assert "datetime.fromtimestamp" in src


def test_the_session_reader_reaches_past_weekends():
    """5 sessions is never 5 calendar days — a Friday-to-Friday window has 2
    weekends and can have a holiday."""
    from app.services.games import price_resolver

    src = inspect.getsource(price_resolver.recent_nifty_session_closes)
    assert "days=n * 3 + 12" in src
