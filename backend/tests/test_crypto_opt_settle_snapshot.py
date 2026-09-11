"""Crypto option settlement must not depend on the position's instrument snapshot.

The snapshot embedded in a crypto option Position carries no expiry, strike or
option type, so the settlement sweep skipped every one: 11-Sep contracts stayed
OPEN past the 13:30 settle, a 6-Sep one five days on. The sweep now reads those
from the Instrument row, and refuses to guess a price for a contract long past
expiry (its intrinsic would come off today's spot, not its own expiry's).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.services import expiry_cleanup as ec

SPOT = Decimal("77427.54")


def _run(expiry_dt_ist, monkeypatch):
    token = "BTC-X-79000-P"
    snap = SimpleNamespace(token=token, expiry=None, strike=None, option_type=None, underlying_token=None)
    pos = SimpleNamespace(id="p1", instrument=snap)
    row = SimpleNamespace(
        expiry=datetime.combine(expiry_dt_ist.date(), datetime.min.time()),
        strike=Decimal("79000"),
        option_type="PE",
        underlying_token="CRYPTO_BTCUSD",
    )

    class _Find:
        async def to_list(self):
            return [pos]

    class _Inst:
        token = object()

        @staticmethod
        async def find_one(*_a, **_kw):
            return row

    calls = []

    async def ltp(tok):
        return SPOT if tok == "CRYPTO_BTCUSD" else Decimal("0")  # option feed is gone

    async def settle(p, *, settlement_price, allow_zero, reason):
        calls.append((settlement_price, reason))
        return "settled"

    async def settle_time():
        return expiry_dt_ist.time().replace(microsecond=0)

    from app.models import position as _pm
    from app.services import crypto_expiry_settings, market_data_service, position_service

    monkeypatch.setattr(_pm.Position, "find", lambda *_a, **_kw: _Find())
    monkeypatch.setattr(ec, "Instrument", _Inst)
    monkeypatch.setattr(market_data_service, "get_ltp", ltp)
    monkeypatch.setattr(position_service, "settle_expired_position", settle)
    monkeypatch.setattr(crypto_expiry_settings, "settle_time_ist", settle_time)
    res = asyncio.run(ec.settle_expired_crypto_options())
    return res, calls


def test_settles_when_the_snapshot_has_no_expiry(monkeypatch):
    an_hour_ago = datetime.now(ec.IST) - timedelta(hours=1)
    res, calls = _run(an_hour_ago, monkeypatch)
    assert res == {"settled": 1}
    # Put, strike 79000, spot 77427.54 -> intrinsic 1572.46, reason = expiry.
    assert calls == [(Decimal("79000") - SPOT, "CRYPTO_OPT_EXPIRY")]


def test_does_not_guess_a_price_for_a_long_expired_contract(monkeypatch):
    five_days_ago = datetime.now(ec.IST) - timedelta(days=5)
    res, calls = _run(five_days_ago, monkeypatch)
    assert res == {"settled": 0}
    assert calls == []
