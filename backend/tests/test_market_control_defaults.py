"""A market-control row offers the session that segment actually trades.

The operator set a 30-second opening delay — MCX from 09:00:30, NSE from
09:15:30 — and reported it not working. Checked live at 09:04 IST:

    NSE_EQ        False   "Market opens at 09:15:30 IST for this segment"
    NSE_STK_FUT   False   "Market opens at 09:15:30 IST for this segment"
    MCX_FUT       None    —
    MCX_OPT       None    —

NSE works. MCX returns no opinion because no MCX row was ever saved, so the
gate falls through to the built-in calendar, which opens MCX at 09:00:00
flat with no delay anywhere in it. The parser handles seconds, the segment
mapping is right, the gate compares at second precision — nothing in that
chain was broken.

What WAS wrong is the pre-fill those unsaved rows show. Every segment
offered 09:15 → 15:30, which is only true of NSE and BSE. Enabling MCX
without first retyping both fields would have set a market that runs
09:00–23:30 to 09:15–15:30 — six hours of session gone from a toggle that
looked like it was only turning the window ON. Crypto and Forex had the same
trap: a 24-hour book cut to the Indian equity bell.

So the toggle alone is now correct, and a time is typed only when the
operator actually wants to change one.
"""

from __future__ import annotations

from app.api.v1.admin.market_control import _OPTION_SEGMENTS, _row_out
from app.models.netting import SEGMENT_CODES


def _d(code: str) -> tuple[str, str]:
    r = _row_out(code, None)
    return r["open_time"], r["close_time"]


# ── the segment that started this ──────────────────────────────────────
def test_mcx_defaults_to_its_own_session():
    assert _d("MCX_FUT") == ("09:00", "23:30")


def test_mcx_options_close_just_before_the_mcx_bell():
    """Not before the NSE one. The 30-second lead has to be measured from
    the close that segment actually has."""
    assert _d("MCX_OPT") == ("09:00", "23:29:30")


# ── the ones that were already right ──────────────────────────────────
def test_nse_and_bse_are_unchanged():
    assert _d("NSE_EQ") == ("09:15", "15:30")
    assert _d("BSE_EQ") == ("09:15", "15:30")


def test_indian_options_still_lead_the_equity_bell_by_thirty_seconds():
    assert _d("NSE_IDX_OPT") == ("09:15", "15:29:30")
    assert _d("NSE_STK_OPT") == ("09:15", "15:29:30")
    assert _d("BSE_OPT") == ("09:15", "15:29:30")


# ── the round-the-clock books ─────────────────────────────────────────
def test_crypto_and_forex_default_to_the_whole_day():
    """Enabling one of these to change a single time must not quietly close
    it at the Indian equity bell."""
    for code in ("CRYPTO", "CRYPTO_OPT", "FOREX"):
        assert _d(code)[0] == "00:00", code
        assert _d(code)[1].startswith("23:5"), code


# ── invariants across the whole catalogue ─────────────────────────────
def test_every_segment_offers_a_default():
    for code in SEGMENT_CODES:
        o, c = _d(code)
        assert o and c, code


def test_no_segment_opens_after_it_closes():
    for code in SEGMENT_CODES:
        o, c = _d(code)
        assert o < c, code


def test_every_option_segment_closes_before_its_own_futures_segment():
    """An option row that closed AFTER its underlying would be the opposite
    of the rule it exists for."""
    pairs = (("NSE_IDX_OPT", "NSE_IDX_FUT"), ("NSE_STK_OPT", "NSE_STK_FUT"),
             ("BSE_OPT", "BSE_FUT"), ("MCX_OPT", "MCX_FUT"))
    for opt, fut in pairs:
        assert opt in _OPTION_SEGMENTS
        assert _d(opt)[1] < _d(fut)[1], opt


def test_a_saved_row_always_wins_over_the_default():
    """These are pre-fills, nothing more. A saved window is the operator's
    and must come back exactly as typed, seconds included."""
    from types import SimpleNamespace

    # A stand-in, not the Beanie document — `_row_out` only ever reads these
    # three fields, and the real model needs a live collection to exist.
    saved = SimpleNamespace(enabled=True, open_time="09:00:30", close_time="23:30:00")
    r = _row_out("MCX_FUT", saved)
    assert r["open_time"] == "09:00:30"
    assert r["close_time"] == "23:30:00"
    assert r["enabled"] is True


def test_the_gate_reads_seconds_out_of_a_saved_window():
    """The whole point of the exercise: 09:00:30 has to mean 09:00:30, not
    09:00."""
    from datetime import time

    from app.utils.time_utils import parse_hhmm

    assert parse_hhmm("09:00:30") == time(9, 0, 30)
    assert parse_hhmm("09:15:30") == time(9, 15, 30)
    assert parse_hhmm("09:00") == time(9, 0)
    # And a second before open is still shut.
    assert time(9, 0, 29) < parse_hhmm("09:00:30")
