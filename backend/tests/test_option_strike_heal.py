"""SELL on NIFTY26N0323700CE was refused with "Strike-based sell margin isn't
configured (missing strike or rate)". The rate was set; the row had no strike,
because it was mirrored from a bare on-demand subscription (token + symbol).
1,254 option rows were like that. get_by_token now fills the strike from the
catalog, and a miss is not rescanned on every call."""

import asyncio
import types

from bson import Decimal128

from app.services import instrument_service as svc

TOKEN = "13849090"


def _row(strike=None, active=True):
    return types.SimpleNamespace(
        token=TOKEN, symbol="NIFTY26N0323700CE", option_type="CE", strike=strike,
        is_active=active, is_tradable=active,
    )


def _wire(monkeypatch, row, catalog_strike):
    calls = []

    async def find_one(*_a, **_kw):
        return row

    async def mirror(token, existing=None):
        calls.append(token)
        if catalog_strike is None:
            return None
        existing.strike = Decimal128(catalog_strike)
        return existing

    # Beanie is not initialised in unit tests, so stand in for the model.
    monkeypatch.setattr(svc, "Instrument", types.SimpleNamespace(token=None, find_one=find_one))
    monkeypatch.setattr(svc, "_mirror_from_zerodha", mirror)
    monkeypatch.setattr(svc, "_needs_recycle_check", lambda _t: False)
    svc._STRIKE_HEAL_TRIED.pop(TOKEN, None)
    return calls


def test_a_live_option_without_strike_is_filled_from_the_catalog(monkeypatch):
    calls = _wire(monkeypatch, _row(), "23700")
    inst = asyncio.run(svc.get_by_token(TOKEN))
    assert str(inst.strike) == "23700" and calls == [TOKEN]


def test_a_catalog_miss_is_not_rescanned_on_every_call(monkeypatch):
    calls = _wire(monkeypatch, _row(), None)
    asyncio.run(svc.get_by_token(TOKEN))
    asyncio.run(svc.get_by_token(TOKEN))
    assert calls == [TOKEN]


def test_rows_with_a_strike_or_retired_rows_are_left_alone(monkeypatch):
    calls = _wire(monkeypatch, _row(strike=Decimal128("23700")), "1")
    asyncio.run(svc.get_by_token(TOKEN))
    assert calls == []
    calls = _wire(monkeypatch, _row(active=False), "23700")
    asyncio.run(svc.get_by_token(TOKEN))
    assert calls == []
