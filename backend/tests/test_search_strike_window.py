"""ATM strike window on the instrument BROWSE/SEARCH path.

The window used to be applied only by the option-chain endpoint. The
marketwatch "MCX OPT" / "CRYPTO OPT" / "NSE OPT" chips come through
`/instruments/search` instead, which had no strike filtering at all — so
setting MCX Option = 2 appeared to do nothing.

Failing OPEN is the load-bearing property here: a cold catalog or a feed gap
must leave the panel populated, never blank it.
"""

from __future__ import annotations

from datetime import date

import pytest

import app.api.v1.user.option_chain as oc
from app.api.v1.user.instruments import _cap_options_by_atm_window

EXPIRY = date(2026, 8, 18)

ACCESSORS = dict(
    get_it=lambda r: r["it"],
    get_root=lambda r: r["root"],
    get_exp=lambda r: r["exp"],
    get_ex=lambda r: r["ex"],
    get_strike=lambda r: r["strike"],
)


def _opt(strike, it="CE", root="CRUDEOIL", ex="MCX", exp=EXPIRY):
    return {"it": it, "root": root, "ex": ex, "exp": exp, "strike": strike}


def _fut(root="CRUDEOIL", ex="MCX"):
    return {"it": "FUT", "root": root, "ex": ex, "exp": EXPIRY, "strike": None}


def _patch(monkeypatch, allowed, window=2):
    async def _fake(root, expiry, exchange):
        return (allowed, window)

    monkeypatch.setattr(oc, "allowed_strike_set", _fake)


async def test_out_of_window_strikes_are_dropped(monkeypatch):
    _patch(monkeypatch, {5700.0, 5750.0, 5800.0, 5850.0, 5900.0})
    rows = [_opt(s) for s in (5500, 5700, 5800, 5900, 6200)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert [r["strike"] for r in out] == [5700, 5800, 5900]


async def test_futures_and_equities_pass_through(monkeypatch):
    _patch(monkeypatch, {5800.0})
    rows = [_fut(), _opt(5800), _opt(9999)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert out[0]["it"] == "FUT"
    assert [r["strike"] for r in out[1:]] == [5800]


async def test_order_is_preserved(monkeypatch):
    _patch(monkeypatch, {5700.0, 5800.0, 5900.0})
    rows = [_opt(5900), _opt(5700), _opt(5800)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert [r["strike"] for r in out] == [5900, 5700, 5800]


async def test_fails_open_when_window_unresolvable(monkeypatch):
    """Cold catalog / no spot → every row survives, panel never blanks."""
    _patch(monkeypatch, None)
    rows = [_opt(s) for s in (5500, 5800, 6200)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert len(out) == 3


async def test_fails_open_when_resolver_raises(monkeypatch):
    async def _boom(root, expiry, exchange):
        raise RuntimeError("catalog down")

    monkeypatch.setattr(oc, "allowed_strike_set", _boom)
    rows = [_opt(s) for s in (5500, 5800, 6200)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert len(out) == 3


async def test_unparseable_strike_is_kept(monkeypatch):
    _patch(monkeypatch, {5800.0})
    rows = [_opt("not-a-number"), _opt(5800)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert len(out) == 2


async def test_decimal128_strike_is_matched(monkeypatch):
    """Mongo rows carry bson.Decimal128, which float() refuses outright."""
    from bson import Decimal128

    _patch(monkeypatch, {5800.0})
    rows = [_opt(Decimal128("5800.00")), _opt(Decimal128("6200.00"))]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert len(out) == 1


async def test_each_underlying_expiry_resolved_once(monkeypatch):
    """The ladder scan is expensive — it must not run per row."""
    calls: list = []

    async def _counting(root, expiry, exchange):
        calls.append((root, expiry))
        return ({5800.0}, 2)

    monkeypatch.setattr(oc, "allowed_strike_set", _counting)
    rows = [_opt(5800) for _ in range(50)] + [_opt(5800, root="GOLD")]
    await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert len(calls) == 2


async def test_no_options_is_a_noop(monkeypatch):
    called = False

    async def _fake(root, expiry, exchange):
        nonlocal called
        called = True
        return (set(), 2)

    monkeypatch.setattr(oc, "allowed_strike_set", _fake)
    rows = [_fut(), _fut(root="GOLD")]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert out == rows and called is False


@pytest.mark.parametrize("bad_exp", [None, ""])
async def test_option_without_expiry_passes_through(monkeypatch, bad_exp):
    _patch(monkeypatch, {5800.0})
    rows = [_opt(9999, exp=bad_exp)]
    out = await _cap_options_by_atm_window(rows, **ACCESSORS)
    assert len(out) == 1
