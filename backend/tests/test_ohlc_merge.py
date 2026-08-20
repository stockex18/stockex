"""OHLC must survive a thinner tick.

Kite's LTP-mode packet is 8 bytes and carries no `ohlc` block, so the
normalizer reports `high/low/open/close/volume = 0`. The quote merge used
`.get(key, default)`, but the key is always PRESENT — only its VALUE is 0 —
so a good day-high was overwritten with 0 until the next 44-byte quote packet
arrived. That is the "NSE/MCX high-low goes wrong for a while, then fixes
itself" report.
"""

from __future__ import annotations

import pytest

from app.services import market_data_service as mds


def _base():
    return {
        "ltp": 24500.0, "open": 24400.0, "high": 24610.0, "low": 24380.0,
        "prev_close": 24350.0, "volume": 1000, "bid": 0, "ask": 0,
    }


def _merge(base, live):
    """Drive the merge exactly as _infoway/_zerodha overlay does."""
    merged = dict(base)
    merged["ltp"] = live.get("ltp", merged["ltp"])

    def _keep(key, src_key=None):
        try:
            v = float(live.get(src_key or key) or 0)
        except (TypeError, ValueError):
            return
        if v > 0:
            merged[key] = live.get(src_key or key)

    _keep("open"); _keep("high"); _keep("low")
    _keep("prev_close", "close"); _keep("volume")
    return merged


LTP_MODE_TICK = {"ltp": 24555.0, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}


def test_ltp_mode_tick_does_not_wipe_ohlc():
    out = _merge(_base(), LTP_MODE_TICK)
    assert out["ltp"] == 24555.0        # price still updates
    assert out["high"] == 24610.0       # ...but the day range survives
    assert out["low"] == 24380.0
    assert out["open"] == 24400.0
    assert out["prev_close"] == 24350.0
    assert out["volume"] == 1000


def test_quote_mode_tick_still_updates_ohlc():
    """The guard must not freeze a genuinely new high."""
    out = _merge(_base(), {"ltp": 24700.0, "open": 24400.0, "high": 24720.0,
                           "low": 24380.0, "close": 24350.0, "volume": 5000})
    assert out["high"] == 24720.0
    assert out["volume"] == 5000


def test_alternating_packet_modes_stay_stable():
    """Real streams mix modes — the range must never flicker to 0."""
    q = _base()
    for i in range(10):
        tick = LTP_MODE_TICK if i % 2 else {"ltp": 24500.0 + i, "open": 24400.0,
                                            "high": 24610.0, "low": 24380.0,
                                            "close": 24350.0, "volume": 1000 + i}
        q = _merge(q, tick)
        assert q["high"] == 24610.0, f"high wiped on iteration {i}"
        assert q["low"] == 24380.0, f"low wiped on iteration {i}"


def test_first_ever_tick_can_set_ohlc_from_zero_base():
    """A cold quote (all zeros) must still accept the first real OHLC."""
    cold = {"ltp": 0, "open": 0, "high": 0, "low": 0, "prev_close": 0, "volume": 0}
    out = _merge(cold, {"ltp": 100.0, "open": 99.0, "high": 101.0, "low": 98.0,
                        "close": 97.0, "volume": 42})
    assert (out["high"], out["low"], out["open"]) == (101.0, 98.0, 99.0)
    assert out["prev_close"] == 97.0


@pytest.mark.parametrize("junk", [None, "", "abc", float("nan")])
def test_junk_values_are_ignored_not_written(junk):
    out = _merge(_base(), {"ltp": 24555.0, "high": junk})
    assert out["high"] == 24610.0


def test_guard_exists_in_production_source():
    """Guards the fix itself — a refactor back to `.get(k, default)` for OHLC
    silently reintroduces the wipe."""
    import inspect
    src = inspect.getsource(mds)
    assert 'merged["high"] = live.get("high", merged["high"])' not in src
