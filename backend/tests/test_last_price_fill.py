"""After the bell, an order still needs a price to fill against.

Operator: "after 3:30 it's not taking any trades ... 3.41 tak trade ho".

Market Control was already holding the NSE window open to 15:40, so the
hours gate was not the blocker. The PRICE was. The feed stops ticking at
15:30, `mdlive` lapses ~30 s later, and the matching engine's zero-price guard
then rejected every new order with

    "Market data feed is stale (price unavailable)."   code=STALE_FEED

The guard had a fallback to `mdlast` but only for SQUAREOFF orders, so a user
could close a position after the bell but not open one. Meanwhile
`ALLOW_TRADE_AT_LAST_PRICE` was already True — the platform was configured to
trade at the last known price, and the engine was not honouring it.

This is only safe now because `mdlast` is written on every tick alongside
`mdlive`. It used to freeze for days once a token was served from the mirror,
which is what produced the EICHERMOT wrong-price report; filling against that
would have been far worse than refusing.
"""

from __future__ import annotations

import inspect

from app.services import matching_engine as me


def _guard() -> str:
    src = inspect.getsource(me)
    i = src.index("Sanity guard: NEVER fill at zero")
    return src[i : i + 7000]


def test_an_opening_order_may_use_the_last_known_price():
    g = _guard()
    assert "ALLOW_TRADE_AT_LAST_PRICE" in g
    assert "if order.is_squareoff or _allow_last:" in g


def test_a_squareoff_keeps_its_own_fallback():
    """It never depended on the setting and must not start to — a user has to
    be able to flatten whatever the configuration says."""
    assert "order.is_squareoff or _allow_last" in _guard()


def test_zero_is_still_never_a_fill_price():
    """The danger the guard exists for. An MCX position at avg 8631 once closed
    at 0 and booked -17 lakh when the feed flatlined. `mdlast` is a real recent
    price or nothing — it is read, checked, and only then used."""
    g = _guard()
    assert "_last_val > 0" in g
    assert 'code="STALE_FEED"' in g


def test_it_still_rejects_when_there_is_no_last_price_either():
    g = _guard()
    assert "if not _used_last_ltp and (fill_price is None or fill_price <= Decimal(\"0\")):" in g
    assert "matching_engine_zero_price_blocked" in g


def test_using_a_held_price_is_logged():
    """A fill that did not come from a live tick has to say so."""
    g = _guard()
    assert "matching_engine_used_last_ltp" in g
    assert '"is_squareoff": bool(order.is_squareoff)' in g


def test_a_missing_setting_falls_back_to_the_old_behaviour():
    """If the config cannot be read, opens go back to being refused rather than
    filling against something unverified."""
    g = _guard()
    assert "_allow_last = False" in g


def test_the_fallback_reads_the_key_the_tick_loop_writes():
    """`mdlast:{token}` — the same key `_write_mdlive_batch` refreshes every
    tick. If these two ever name different keys the fallback goes stale again
    without anything failing."""
    from app.services import market_data_service as mds

    assert 'f"mdlast:{order.instrument.token}"' in _guard()
    assert mds._LAST_QUOTE_KEY == "mdlast:{token}"
    assert "_LAST_QUOTE_KEY.format(token=token)" in inspect.getsource(mds._write_mdlive_batch)


def test_a_disconnected_broker_still_blocks_an_open():
    """Different thing from the market being shut. The validator's
    connectivity gate is what separates them and must stay."""
    from app.services import order_validator as ov

    src = inspect.getsource(ov.validate)
    assert "Zerodha-connectivity gate" in src
