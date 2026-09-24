"""The OFSS regression: a market buy on the ask must not read as mispriced.

24 Sept 2026, OFSS26SEPFUT, 10:33 IST. The exchange traded 10849-10863. Our
own feed printed exactly that, and quoted bid 10846-10862 / ask 10855-10873.
A market BUY filled at 10869 -- on our ask, as a market buy does.

The first cut of Check Trades compared that fill against the candle alone and
called it "above high" by 6 rupees. But a candle's high is a TRADED price, so
the ask is above it by construction: every market buy would have failed and
every market sell too. These are the two numbers the fix turns on.
"""

from decimal import Decimal

from types import SimpleNamespace

from app.services.trade_audit_service import _fill_band, _neighbourhood

# A plain stand-in: `_fill_band` only reads these six numbers, and a real
# TickSnapshot cannot be built without a live Beanie connection.
_SNAP = SimpleNamespace(
    low=10849.0, high=10863.0,
    bid_low=10846.0, bid_high=10862.0,
    ask_low=10855.0, ask_high=10873.0,
)


def test_market_buy_on_our_ask_is_inside_our_own_band():
    lo, hi = _fill_band(_SNAP)
    assert lo == Decimal("10846")
    assert hi == Decimal("10873")
    # The fill the old check flagged. It sat on the ask we published.
    assert lo <= Decimal("10869") <= hi


def test_a_price_we_never_quoted_still_fails():
    lo, hi = _fill_band(_SNAP)
    assert not (lo <= Decimal("10920") <= hi)
    assert not (lo <= Decimal("10800") <= hi)


def test_neighbourhood_spans_the_minute_either_side():
    from datetime import datetime

    day = {
        "10:32": {"l": 10844.0, "h": 10852.0},
        "10:33": {"l": 10849.0, "h": 10863.0},
        "10:34": {"l": 10863.0, "h": 10915.0},
    }
    assert _neighbourhood(day, datetime(2026, 9, 24, 10, 33)) == (
        Decimal("10844"),
        Decimal("10915"),
    )
    # A minute with nothing around it cannot be judged.
    assert _neighbourhood({}, datetime(2026, 9, 24, 10, 33)) is None
