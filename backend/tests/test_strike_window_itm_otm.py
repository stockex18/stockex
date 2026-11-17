"""Each underlying can have its own ITM and OTM strike counts.

Requested by the client so each instrument can have its own ITM / OTM range,
instead of one "strikes around ATM" number per segment used on both sides.
A call is in the money BELOW spot and a put ABOVE it, so the same counts point
opposite ways: a CE may sit from ATM − ITM to ATM + OTM, a PE from ATM − OTM to
ATM + ITM. Anything not set falls back to the segment's value.

Catalog, spot and settings are replaced with fakes; no Mongo / Redis / feed.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from bson import Decimal128

from app.api.v1.user import option_chain as oc
from app.services.order_validator import strike_window_breach

EXPIRY = date(2026, 11, 24)
# NIFTY ladder 24000 … 25000, step 50; spot 24500 → ATM index 10.
LADDER = [float(k) for k in range(24000, 25001, 50)]


def _patch(monkeypatch, *, segment=3, by_underlying=None, spot=24500.0):
    async def _window(_seg):
        return segment

    async def _catalog(_und):
        rows = [{"strike": k, "option_type": "CE", "_expiry_date": EXPIRY} for k in LADDER]
        return (rows, [])

    async def _spot(_und, _ex=None):
        return spot

    async def _setting(key, default):
        if key == oc._STRIKES_BY_UNDERLYING_KEY:
            return by_underlying if by_underlying is not None else default
        return default

    monkeypatch.setattr(oc, "_strikes_around_atm_for", _window)
    monkeypatch.setattr(oc, "_cached_catalog", _catalog)
    monkeypatch.setattr(oc, "_underlying_spot", _spot)
    monkeypatch.setattr(oc, "_read_setting", _setting)


async def _allowed(option_type=None, root="NIFTY"):
    allowed, _ = await oc.allowed_strike_set(root, EXPIRY, "NFO", option_type=option_type)
    return sorted(allowed) if allowed is not None else None


def test_call_and_put_point_opposite_ways():
    assert oc._side_span(2, 5, "CE") == (2, 5)  # ITM below, OTM above
    assert oc._side_span(2, 5, "PE") == (5, 2)  # OTM below, ITM above
    assert oc._side_span(2, 5, None) == (5, 5)  # a whole row: the wider


def test_label_reads_naturally():
    assert oc.window_label(10, 10) == "ATM ±10"
    assert oc.window_label(2, 5) == "2 ITM / 5 OTM"


async def test_unset_underlying_keeps_the_segment_window(monkeypatch):
    _patch(monkeypatch, segment=3)
    assert await _allowed("CE") == LADDER[7:14]  # ATM ± 3
    assert await _allowed("PE") == LADDER[7:14]


async def test_calls_get_itm_below_and_otm_above(monkeypatch):
    _patch(monkeypatch, segment=3, by_underlying={"NIFTY": {"itm": 2, "otm": 5}})
    assert await _allowed("CE") == LADDER[8:16]  # 24400 … 24750


async def test_puts_get_itm_above_and_otm_below(monkeypatch):
    _patch(monkeypatch, segment=3, by_underlying={"NIFTY": {"itm": 2, "otm": 5}})
    assert await _allowed("PE") == LADDER[5:13]  # 24250 … 24600


async def test_other_underlyings_are_untouched(monkeypatch):
    _patch(monkeypatch, segment=3, by_underlying={"NIFTY": {"itm": 2, "otm": 5}})
    assert await _allowed("CE", root="BANKNIFTY") == LADDER[7:14]


async def test_one_side_set_the_other_falls_back(monkeypatch):
    _patch(monkeypatch, segment=3, by_underlying={"NIFTY": {"otm": 6}})
    assert await _allowed("CE") == LADDER[7:17]  # 3 ITM, 6 OTM


async def test_bad_values_fall_back_to_the_segment(monkeypatch):
    _patch(monkeypatch, segment=3, by_underlying={"NIFTY": {"itm": "x", "otm": 0}})
    assert await _allowed("CE") == LADDER[7:14]


async def test_settings_read_failure_fails_open_to_the_segment(monkeypatch):
    _patch(monkeypatch, segment=3)

    async def _boom(_key, _default):
        raise RuntimeError("db down")

    monkeypatch.setattr(oc, "_read_setting", _boom)
    assert await _allowed("CE") == LADDER[7:14]


def _option(strike: float, side: str):
    return SimpleNamespace(
        symbol=f"NIFTY26NOV{int(strike)}{side}",
        expiry=EXPIRY,
        strike=Decimal128(str(strike)),
        option_type=side,
    )


async def test_order_gate_follows_the_side(monkeypatch):
    _patch(monkeypatch, segment=3, by_underlying={"NIFTY": {"itm": 2, "otm": 5}})
    # 24700 is 4 strikes above ATM: OTM for a call (allowed, 5 OTM) …
    assert await strike_window_breach(_option(24700, "CE"), "NFO") is None
    # … but ITM for a put (only 2 ITM allowed) → close-only.
    assert await strike_window_breach(_option(24700, "PE"), "NFO") is not None


def test_chain_rows_blank_the_leg_outside_its_window():
    rows = [{"strike": k, "ce": {"s": "c"}, "pe": {"s": "p"}} for k in LADDER[5:16]]  # ATM ± 5
    out = oc._trim_legs_to_side_windows(rows, 5, itm=2, otm=5)
    by_strike = {r["strike"]: r for r in out}
    # 3 below ATM: a call there is 3 ITM (> 2) → blank; a put is 3 OTM → kept.
    assert by_strike[24350.0]["ce"] is None and by_strike[24350.0]["pe"] is not None
    # 3 above ATM: a call is 3 OTM → kept; a put is 3 ITM → blank.
    assert by_strike[24650.0]["ce"] is not None and by_strike[24650.0]["pe"] is None
    # ATM keeps both legs.
    assert by_strike[24500.0]["ce"] is not None and by_strike[24500.0]["pe"] is not None


def test_equal_itm_otm_leaves_rows_alone():
    rows = [{"strike": k, "ce": {}, "pe": {}} for k in LADDER[7:14]]
    assert oc._trim_legs_to_side_windows(rows, 3, itm=3, otm=3) is rows
