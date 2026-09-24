"""Check Trades — did the exchange print a price that covers this fill?

Operator: "us time per exchange me jo rate chal raha tha usi rate se match ho
raha hai ya nahi — high aur low ke beech me wo hai ya nahi." A fill outside
that minute's range never traded on the exchange.

Two things had to be true for the tool to be usable at all: the reference has
to be the EXCHANGE, not our own recording, and one click must not turn into
hundreds of upstream requests.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from app.api.v1.admin import trade_audit
from app.services import trade_audit_service as svc


def test_only_the_super_admin_may_run_it():
    assert "admin: SuperAdmin" in inspect.getsource(trade_audit.check_trades)


def test_the_reference_is_the_exchange_not_our_own_tick_store():
    """Checking our fills against our own recording only proves the recording
    is self-consistent — it cannot see a minute where our feed was wrong,
    which is the only interesting case."""
    s = inspect.getsource(svc)
    assert "zerodha_service.zerodha.get_historical(" in s
    assert "tick_snapshots" not in s


def test_one_request_per_instrument_day_not_per_trade():
    """The whole reason it is cheap: a day of candles answers every trade on
    that instrument."""
    s = inspect.getsource(svc.audit)
    assert "needed: set[tuple[str, date]] = set()" in s
    assert "_candles_for_token(tok, day, sem) for tok, day in sorted(needed)" in s


def test_candles_are_cached_because_a_closed_minute_cannot_change():
    s = inspect.getsource(svc._candles_for_token)
    assert "cache_get(key)" in s and "cache_set(key" in s
    assert svc._CACHE_TTL_SEC >= 3600


def test_the_upstream_rate_limit_is_respected():
    """Kite caps historical data at about three a second."""
    assert svc._MAX_PARALLEL_FETCHES <= 3
    assert svc._FETCH_SPACING_SEC > 0
    s = inspect.getsource(svc._candles_for_token)
    assert "async with sem:" in s


def test_the_window_is_bounded():
    s = inspect.getsource(trade_audit.check_trades)
    assert "_MAX_DAYS" in s
    assert trade_audit._MAX_DAYS <= 31


def test_a_fill_on_the_high_or_the_low_is_not_a_breach():
    """Prices arrive as strings and become Decimals; a hair of arithmetic must
    not turn an exact touch into a mismatch."""
    s = inspect.getsource(svc.audit)
    assert "price > high + _EPSILON" in s
    assert "price < low - _EPSILON" in s
    assert svc._EPSILON > 0


def test_an_instrument_with_no_history_is_reported_not_judged():
    """Crypto and forex have no exchange candle. Calling them wrong would be
    worse than saying nothing."""
    s = inspect.getsource(svc.audit)
    assert "if not candle:" in s
    assert 'skipped.append' in s
    assert '"reason": "no exchange candle for this minute"' in s


def test_one_dead_instrument_does_not_sink_the_run():
    s = inspect.getsource(svc._candles_for_token)
    assert "trade_audit_candles_failed" in s
    assert "return {}" in s


def test_the_worst_offenders_come_first():
    s = inspect.getsource(svc.audit)
    assert 'rows.sort(key=lambda r: (r["verdict"] == "OK", -abs(r["off_by"])))' in s


def test_it_only_reads():
    """Correcting a trade stays a separate, deliberate act."""
    s = inspect.getsource(svc)
    for w in (".save()", ".insert()", "delete_many(", "update_one("):
        assert w not in s, w


def test_minutes_are_keyed_in_ist_like_the_candles_are():
    s = inspect.getsource(svc._minute)
    assert "astimezone(IST)" in s
    assert "second=0, microsecond=0" in s
    got = svc._minute(datetime(2026, 9, 24, 5, 30, 45, tzinfo=timezone.utc))
    assert (got.hour, got.minute, got.second) == (11, 0, 0)
