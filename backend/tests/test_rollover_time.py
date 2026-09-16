"""Intraday→carry rollover fire time.

The loop compares `(now.hour, now.minute) >= fire_after` as a TUPLE, so a
minute value that overflows past 59 never matches and the sweep is silently
skipped for the whole day — no carry, no force-close of under-margined
positions. These guard that arithmetic.
"""

from __future__ import annotations

from datetime import time

from app.services.position_service import ROLLOVER_DELAY_MIN, rollover_fire_after

NSE_CLOSE = time(15, 30)
MCX_CLOSE = time(23, 30)


def test_nse_fires_at_1542():
    """Past the closing session's last print, not into it.

    NSE's bell is 15:30 but the closing session keeps trading — on 16 Sep the
    last NIFTY future tick landed at 15:41:57. Sweeping at 15:41 booked two
    BANKNIFTY 56500 legs at the 15:30 prices (549.70 / 647.45) while the
    exchange finished at 546.05 / 658.25. Operator: "3:42 me carry forward
    and clearing, ek min wait karna taki last sahi LTP ask bid mile."
    """
    assert rollover_fire_after(NSE_CLOSE, "INDIAN_EQUITY_FNO") == (15, 42)


def test_mcx_still_fires_one_minute_after_close():
    """The NSE change must not drag MCX along with it."""
    assert rollover_fire_after(MCX_CLOSE, "MCX") == (23, 31)


def test_unknown_group_defaults_to_one_minute():
    assert rollover_fire_after(time(9, 0), "CRYPTO_SOMETHING") == (9, 1)


def test_delay_carries_into_the_hour():
    """15:55 + 12 = 16:07, never the unmatchable 15:67."""
    assert rollover_fire_after(time(15, 55), "INDIAN_EQUITY_FNO") == (16, 7)


def test_never_spills_past_midnight():
    """A late close + delay must still fire the same day, not never."""
    h, m = rollover_fire_after(time(23, 59), "INDIAN_EQUITY_FNO")
    assert (h, m) == (23, 59)
    assert 0 <= m <= 59


def test_every_configured_delay_produces_a_reachable_minute():
    for close_t in (NSE_CLOSE, MCX_CLOSE):
        for group in ROLLOVER_DELAY_MIN:
            h, m = rollover_fire_after(close_t, group)
            assert 0 <= h <= 23, (group, close_t)
            assert 0 <= m <= 59, (group, close_t)
