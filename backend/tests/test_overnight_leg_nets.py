"""Yesterday's position and today's closing leg must meet in one row.

Live, 1 Oct. Three users, same shape every time:

    CL16079629  KPITTECH26OCTFUT    NRML  BUY  +2325   opened 30/09 11:04
                                    MIS   SELL  -775   opened 01/10 09:16
    CL16079629  PERSISTENT26OCTFUT  NRML  BUY   +125   opened 30/09 13:23
                                    MIS   SELL  -125   opened 01/10 09:15

The buy carried over as NRML. The next morning the app sent the closing sell
as MIS, and `apply_fill` matches on (user, token, PRODUCT) -- so it found
nothing to net against and opened a short beside the long. The user is left
holding both sides of a trade they meant to be flat on.

Operator: "10 quantity pehle se hain aur doosre din ya teesre din 10 sell
karta hun to wo close ho jana chahiye, alag se position mat open ho."

The rule is not about equity, and never was: any segment that can hold a
position overnight can be hit by this. These tests pin the behaviour, not the
wording -- an open position decides the product, and only when there is none
does the segment default apply.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.models._base import ProductType
from app.services import order_service


class _Field:
    """Beanie builds queries out of class attributes, so the stand-in has to
    survive `Position.instrument.token == x` being evaluated as an argument."""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, attr):
        return _Field(f"{self.name}.{attr}")

    def __eq__(self, other):
        return f"{self.name}=={other}"


class _FakePosition:
    """Stands in for the Beanie document the resolver looks up."""

    found: object | None = None
    seen: tuple = ()

    user_id = _Field("user_id")
    instrument = _Field("instrument")
    product_type = _Field("product_type")
    status = _Field("status")

    @classmethod
    async def find_one(cls, *conditions):
        cls.seen = conditions
        return cls.found


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(order_service, "Position", _FakePosition)
    _FakePosition.found = None

    def call(segment: str, sent: ProductType, open_as: str | None = None):
        _FakePosition.found = (
            SimpleNamespace(product_type=open_as) if open_as else None
        )
        return asyncio.run(
            order_service.resolve_product_type(
                SimpleNamespace(id="u1"),
                SimpleNamespace(token="t1", segment=segment),
                sent,
            )
        )

    return call


def test_a_futures_leg_joins_yesterdays_overnight_position(resolver):
    """The exact live case: NRML carried over, MIS sent to close it."""
    assert resolver("NSE_FUTURE", ProductType.MIS, open_as="NRML") == ProductType.NRML


def test_the_same_holds_for_commodities(resolver):
    assert resolver("MCX_FUTURE", ProductType.MIS, open_as="NRML") == ProductType.NRML


def test_an_intraday_position_is_not_dragged_into_delivery(resolver):
    """It cuts both ways -- the open row decides, whichever product it is."""
    assert resolver("NSE_FUTURE", ProductType.NRML, open_as="MIS") == ProductType.MIS


def test_equity_with_an_open_position_still_follows_that_position(resolver):
    assert resolver("NSE_EQUITY", ProductType.CNC, open_as="MIS") == ProductType.MIS


def test_a_fresh_equity_order_is_still_delivery(resolver):
    """No open row, so the equity default stands: a share bought is a share
    owned."""
    assert resolver("NSE_EQUITY", ProductType.MIS) == ProductType.CNC


def test_a_fresh_order_anywhere_else_keeps_what_it_asked_for(resolver):
    assert resolver("NSE_FUTURE", ProductType.MIS) == ProductType.MIS
    assert resolver("MCX_FUTURE", ProductType.NRML) == ProductType.NRML


def test_the_lookup_is_not_narrowed_by_product(resolver):
    """Filtering the lookup by product type would make it find only the row
    that already matches -- which is the bug, not the fix."""
    resolver("NSE_FUTURE", ProductType.MIS, open_as="NRML")
    assert not any("product_type" in str(c).lower() for c in _FakePosition.seen)
