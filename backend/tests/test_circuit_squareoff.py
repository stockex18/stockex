"""A locked market is not a market — nothing auto-closes into a circuit.

Operator: "If an upper or lower circuit is hit, the system must not square off
the position", followed by "upper circuit and lower circuit ka logic work nahi
kar raha".

It never did. The daily band was read in exactly two places — `order_validator`
rejects an order priced outside it, and the order panel greys out BUY at the
upper / SELL at the lower — and NO square-off path had ever looked at it. So a
stock pinned at its lower circuit still had its stop-loss, take-profit, margin
call and stop-out fired against a price that is frozen and that nobody can
trade at.

`_squareoff_position` is the single funnel every automatic close goes through,
which is why one guard covers all of them.

Blocking is the safe direction: the price is pinned, so nothing gets worse
while we wait, and the next enforcer tick fires the same close the moment the
band releases. Squaring off INTO a locked market is the move that cannot be
undone.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import order_validator as ov
from app.services import risk_enforcer as re
from app.utils.decimal_utils import to_decimal


class _Ref:
    """What `_squareoff_position` actually has: an InstrumentRef, not the full
    Instrument doc. `_circuit_limits` only reads these three fields."""

    exchange = "NSE"
    token = "2953217"
    symbol = "TCS"


def _band(lc, uc):
    # `**_kw` because the real function now takes the price being judged; a
    # fake that rejects it would raise, `_at_circuit` would swallow that, and
    # every "is held" test here would pass for the wrong reason or fail.
    async def _f(_instrument, **_kw):
        return (
            to_decimal(lc) if lc is not None else None,
            to_decimal(uc) if uc is not None else None,
        )

    return _f


@pytest.fixture
def ref():
    return _Ref()


# ── the band is respected ─────────────────────────────────────────────
async def test_a_price_at_the_upper_circuit_holds_the_squareoff(monkeypatch, ref):
    monkeypatch.setattr(ov, "_circuit_limits", _band("900", "1100"))
    assert await re._at_circuit(ref, to_decimal("1100")) is True


async def test_a_price_at_the_lower_circuit_holds_the_squareoff(monkeypatch, ref):
    monkeypatch.setattr(ov, "_circuit_limits", _band("900", "1100"))
    assert await re._at_circuit(ref, to_decimal("900")) is True


async def test_a_print_a_hair_past_the_band_still_counts(monkeypatch, ref):
    """The band is a hard limit, but a feed can print marginally outside it.
    An `==` test would miss exactly the case this exists for."""
    monkeypatch.setattr(ov, "_circuit_limits", _band("900", "1100"))
    assert await re._at_circuit(ref, to_decimal("1105")) is True
    assert await re._at_circuit(ref, to_decimal("899.5")) is True


async def test_a_price_inside_the_band_squares_off_normally(monkeypatch, ref):
    """The guard must not become a reason risk management stops working."""
    monkeypatch.setattr(ov, "_circuit_limits", _band("900", "1100"))
    assert await re._at_circuit(ref, to_decimal("1000")) is False


# ── it fails open ─────────────────────────────────────────────────────
async def test_an_instrument_with_no_published_band_is_not_held(monkeypatch, ref):
    """Crypto, forex and metals have no circuit at all."""
    monkeypatch.setattr(ov, "_circuit_limits", _band(None, None))
    assert await re._at_circuit(ref, to_decimal("1000")) is False


async def test_a_broken_lookup_does_not_block_risk_management(monkeypatch, ref):
    """Same fail-open rule the validator uses. A Redis or Kite hiccup must not
    quietly switch off every stop-out on the platform."""

    async def boom(_i):
        raise RuntimeError("redis down")

    monkeypatch.setattr(ov, "_circuit_limits", boom)
    assert await re._at_circuit(ref, to_decimal("1000")) is False


async def test_an_unusable_price_is_not_treated_as_a_circuit(monkeypatch, ref):
    """0 means 'no price', not 'at the lower band'. Reading it as a circuit
    would hold every square-off whenever the feed blinked."""
    monkeypatch.setattr(ov, "_circuit_limits", _band("900", "1100"))

    async def zero_ltp(_t):
        return to_decimal(0)

    from app.services import market_data_service as mds

    monkeypatch.setattr(mds, "get_ltp", zero_ltp)
    assert await re._at_circuit(ref, to_decimal(0)) is False


# ── it is wired into the one funnel ───────────────────────────────────
def test_the_guard_sits_in_the_squareoff_funnel():
    """SL, TP, margin call and stop-out all place their order through
    `_squareoff_position`. One guard, all of them."""
    src = inspect.getsource(re._squareoff_position)
    assert "if await _at_circuit(p.instrument, fill_at):" in src
    # the guard bails out rather than falling through into the order
    i = src.index("if await _at_circuit(")
    j = src.index("action = OrderAction.SELL", i)
    assert "return" in src[i:j]
    # and it happens BEFORE the order is built
    assert src.index("_at_circuit") < src.index("order_service.place_order")


def test_holding_a_squareoff_is_logged():
    """A position that should have closed and did not has to leave a record,
    or the next question about it is unanswerable."""
    src = inspect.getsource(re._squareoff_position)
    assert "risk_squareoff_held_at_circuit" in src


def test_the_band_comes_from_the_same_place_the_validator_uses():
    """One source for the band. A second copy would drift, and then the panel,
    the validator and the enforcer would disagree about what a circuit is."""
    src = inspect.getsource(re._at_circuit)
    assert "from app.services.order_validator import _circuit_limits" in src


def test_the_validator_still_blocks_orders_outside_the_band():
    """The pre-existing half. This commit adds to it, it does not replace it."""
    src = inspect.getsource(ov.validate)
    assert 'code="UPPER_CIRCUIT"' in src
    assert 'code="LOWER_CIRCUIT"' in src
