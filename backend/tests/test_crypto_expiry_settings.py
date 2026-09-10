"""Crypto option expiry: how long a contract runs, and when it settles.

Asked for: "crypto ka expiry ka setting — option ka day set karunga kitne din
ka expiry chalega, aur trade automatic 11 baje set kiya, crypto ke baad hote
hi LTP me close ho jaye if position open rahegi."

Three things were fixed to make that possible.

WHEN. The settlement clock was hardcoded at 08:00 UTC — Binance's own — with
no way to move it. It is a setting now, read as an IST clock time, and 13:30
IST (= 08:00 UTC) is the default so an operator who never opens it sees no
change.

HOW OFTEN. The sweep ran on the hourly expiry-cleanup tick. An hourly tick
cannot honour a clock time: set 11:00 and the position closes whenever the
hour comes round, up to an hour late. It has its own minute-resolution loop
now, with the hourly one kept as a backstop.

AT WHAT PRICE. It settled at INTRINSIC. The operator asked for LTP, so LTP it
is — but falling back to intrinsic when there is no live LTP, never to the
last quoted premium. Settling an out-of-the-money option at a stale premium
pays the buyer for a contract that expired worthless. On a live book the two
agree anyway, since an option's mark AT expiry IS its intrinsic.

The tenor is a cap, not a creation: Binance lists the contracts and the dates
are theirs, so "kitne din" hides the longer-dated ones rather than inventing
an expiry.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import time as _time

from app.services import crypto_expiry_settings as ces
from app.services import expiry_cleanup
from app.services import binance_options_service as binance


SETTLE = inspect.getsource(expiry_cleanup.settle_expired_crypto_options)


def _read(monkeypatch, values: dict):
    async def fake(key, default):
        return values.get(key, default)

    ces.invalidate()
    monkeypatch.setattr(ces, "_read", fake)


# ── the settlement clock ────────────────────────────────────────────────────

def test_the_settle_time_is_configurable(monkeypatch):
    _read(monkeypatch, {ces.SETTLE_TIME_KEY: "11:00"})
    assert asyncio.run(ces.settle_time_ist()) == _time(11, 0)


def test_the_default_is_the_old_hardcoded_behaviour(monkeypatch):
    # 08:00 UTC == 13:30 IST. Nobody who ignores the setting sees a change.
    _read(monkeypatch, {})
    assert asyncio.run(ces.settle_time_ist()) == _time(13, 30)


def test_a_typo_does_not_stop_settlement(monkeypatch):
    # A bad value must fall back, not raise — settlement is not the place to
    # discover a malformed setting.
    _read(monkeypatch, {ces.SETTLE_TIME_KEY: "not a time"})
    assert asyncio.run(ces.settle_time_ist()) == _time(13, 30)


def test_the_hardcoded_utc_hour_is_gone():
    assert "_BINANCE_OPT_EXPIRY_UTC_HOUR" not in inspect.getsource(expiry_cleanup)
    assert "settle_time_ist()" in SETTLE


# ── it has to be checked at clock resolution ────────────────────────────────

def test_settlement_runs_on_its_own_minute_loop():
    src = inspect.getsource(expiry_cleanup.crypto_settlement_loop)
    assert "settle_expired_crypto_options()" in src
    assert inspect.signature(expiry_cleanup.crypto_settlement_loop).parameters[
        "interval_sec"
    ].default == 60.0


def test_the_hourly_sweep_is_kept_as_a_backstop():
    src = inspect.getsource(expiry_cleanup.expiry_cleanup_loop)
    assert "settle_expired_crypto_options()" in src


def test_the_loop_is_started_and_stopped():
    import app.main as _m

    src = inspect.getsource(_m)
    assert "crypto_settlement_loop" in src
    assert "stop_crypto_settlement()" in src


# ── price ───────────────────────────────────────────────────────────────────

def test_it_settles_at_the_option_s_own_ltp():
    assert "get_ltp(inst.token)" in SETTLE


def test_a_missing_ltp_falls_back_to_intrinsic_not_a_stale_premium():
    i = SETTLE.index("get_ltp(inst.token)")
    tail = SETTLE[i:]
    assert "if px <= ZERO:" in tail
    assert "max(ZERO, spot - strike)" in tail
    assert "max(ZERO, strike - spot)" in tail


def test_neither_price_means_retry_not_settle_at_zero():
    # Settling at 0 because the feed was quiet would wipe a real ITM position.
    assert "continue  # neither price — retry next sweep" in SETTLE


# ── the tenor cap ───────────────────────────────────────────────────────────

def test_the_days_cap_filters_the_listed_expiries(monkeypatch):
    _read(monkeypatch, {ces.MAX_DAYS_KEY: 7})
    assert asyncio.run(ces.max_days()) == 7
    src = inspect.getsource(binance.BinanceOptionsService.refresh_universe)
    assert "cutoff = today + _timedelta(days=_max_days)" in src


def test_no_cap_leaves_the_universe_alone(monkeypatch):
    _read(monkeypatch, {})
    assert asyncio.run(ces.max_days()) == 0
    src = inspect.getsource(binance.BinanceOptionsService.refresh_universe)
    assert "if _max_days > 0:" in src


def test_saving_drops_the_cache_so_it_is_live_next_tick():
    src = inspect.getsource(
        __import__("app.api.v1.admin.settings", fromlist=["x"]).update_platform_setting
    )
    assert "_ces.invalidate()" in src


def test_the_setting_is_the_super_admin_s():
    src = inspect.getsource(
        __import__("app.api.v1.admin.settings", fromlist=["x"]).update_platform_setting
    )
    assert 'key.startswith("crypto_expiry.")' in src
    assert "_require_super_admin(admin)" in src
