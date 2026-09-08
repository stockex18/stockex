"""The client must gate on the admin's window, not one baked into its bundle.

Operator, with the admin panel open beside it: every NSE/BSE row ON and closing
at 03:41:00 PM, and the phone card still refusing with "NSE market is closed.
Try placing an AMO instead."

The server was right. `lib/marketHours.ts` carried its own calendar -

    return min >= 9 * 60 + 15 && min <= 15 * 60 + 30;   // NSE/BSE

- and `TradeDetailSheet` asked it BEFORE submitting, so the order never reached
the backend that was happily accepting it. A window compiled into a bundle goes
stale the moment somebody edits it in the panel, which is exactly what happened.
"""

from __future__ import annotations

import inspect
import io

MH = r"D:\stockex_new\frontend-user\lib\marketHours.ts"
SHEET = r"D:\stockex_new\frontend-user\components\trading\TradeDetailSheet.tsx"
PANEL = r"D:\stockex_new\frontend-user\components\trading\OrderPanel.tsx"


def src(p: str) -> str:
    return io.open(p, encoding="utf-8", errors="ignore").read()


# ── the server now says what the window is ────────────────────────────
def test_the_settings_endpoint_sends_the_window():
    from app.api.v1.user import segment_settings as ss

    s = inspect.getsource(ss)
    for field in ("market_control_enabled", "market_open", "market_close"):
        assert f'"{field}"' in s, field


def test_it_reads_the_same_row_the_order_gate_reads():
    """`market_control_reason` resolves the segment through `_seg_name_for`.
    Resolving it any other way here would hand the client a different row than
    the one that will actually judge its order."""
    from app.api.v1.user import segment_settings as ss

    s = inspect.getsource(ss)
    assert "MarketControl.segment_name" in s
    assert "_seg_name_for(instrument.segment" in s


def test_a_missing_row_does_not_break_the_settings_read():
    """This hangs off a call the order panel makes three times a second."""
    from app.api.v1.user import segment_settings as ss

    s = inspect.getsource(ss)
    i = s.index("_mc_enabled, _mc_open, _mc_close = False, None, None")
    assert "except Exception" in s[i : i + 900]


# ── the client honours it ─────────────────────────────────────────────
def test_the_guard_accepts_a_server_window():
    s = src(MH)
    assert "window?: MarketWindow," in s
    assert "if (window?.market_control_enabled) {" in s


def test_the_server_window_wins_over_the_builtin_calendar():
    """The calendar is a guess at what the exchange does; the admin's window is
    what the server enforces. When it is on, nothing below it should run."""
    s = src(MH)
    i = s.index("if (window?.market_control_enabled) {")
    j = s.index("return min >= 9 * 60 + 15")
    assert i < j, "the override must be tested before the NSE fallback"


def test_control_switched_off_falls_back_to_the_calendar():
    """`enabled=false` means no override — the same thing the server does."""
    s = src(MH)
    assert "window?.market_control_enabled" in s
    assert "return min >= 9 * 60 + 15 && min <= 15 * 60 + 30;" in s


def test_a_weekend_still_closes_an_indian_segment():
    """The admin sets HOURS, not days. A 09:15-15:41 window must not make
    Saturday tradeable."""
    s = src(MH)
    i = s.index("if (window?.market_control_enabled) {")
    block = s[i : i + 1400]
    assert "if (indian && !weekday) return false;" in block


def test_an_unparseable_time_falls_through_rather_than_blocking_everything():
    """A malformed row must not close the market for every user."""
    s = src(MH)
    assert "if (o !== null || c !== null) {" in s
    assert "function _hhmmToMinutes(" in s


def test_seconds_in_the_stored_time_are_tolerated():
    """The rows are stored "15:41:00", not "15:41"."""
    s = src(MH)
    assert "/^(\d{1,2}):(\d{2})/" in s


# ── both order surfaces pass it ───────────────────────────────────────
def test_the_mobile_card_and_the_desktop_panel_both_pass_the_window():
    for p in (SHEET, PANEL):
        s = src(p)
        i = s.index("!isInstrumentMarketOpen(")
        block = s[i : i + 700]
        assert "effSettings as any," in block, p
        assert "new Date()," in block, p
