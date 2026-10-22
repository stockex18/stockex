"""A Zerodha subscription that only knows its token must never become an
Instrument row. By 22 Oct there were 759 "NSE_EQUITY, lot 1" rows named after
their token — NIFTY / SENSEX / GOLD options, AXISBANK, MARUTI — and the mirror
overwrote good rows with them."""

import asyncio
import inspect
import types

import app.models.instrument as instrument_model
from app.models.zerodha_settings import SubscribedInstrument
from app.services import zerodha_service
from app.services.zerodha_service import zerodha


def _boom(*a, **kw):
    raise AssertionError("the Instrument collection must not be touched")


def test_a_token_named_subscription_is_never_mirrored(monkeypatch):
    monkeypatch.setattr(instrument_model.Instrument, "find_one", _boom)
    for sym in ("13144066", ""):
        sub = SubscribedInstrument(token=13144066, symbol=sym, exchange="NSE")
        assert asyncio.run(zerodha._mirror_subscription_to_instrument(sub)) is None


def test_a_named_subscription_still_reaches_the_mirror(monkeypatch):
    reached = []

    def find_one(*a, **kw):
        reached.append(1)
        raise RuntimeError("stop here")

    monkeypatch.setattr(instrument_model.Instrument, "find_one", find_one)
    # (beanie sets the field expression at init; tests run without a DB)
    monkeypatch.setattr(instrument_model.Instrument, "token", "token", raising=False)
    sub = SubscribedInstrument(token=13144066, symbol="NIFTY26OCT22800CE", exchange="NFO")
    try:
        asyncio.run(zerodha._mirror_subscription_to_instrument(sub))
    except Exception:  # noqa: BLE001
        pass
    assert reached


def test_on_demand_subscribe_does_not_save_unknown_contracts():
    src = inspect.getsource(zerodha_service.ZerodhaService.subscribe_tokens_on_demand)
    assert 'if not meta.get("symbol") or str(meta.get("symbol")) == str(t):' in src
    assert 'symbol=meta.get("symbol") or str(t)' not in src
