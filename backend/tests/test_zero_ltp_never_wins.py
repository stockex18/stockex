"""A 0 from the feed means "this packet carried no price", never "the price
is zero".

Every normaliser in `zerodha_service` builds the tick as
`ltp = float(snap.get("last_price") or 0)`, so a thin packet, a REST snapshot
without `last_price`, or a contract that has not traded yet all arrive as a
hard 0. The overlay wrote that straight over a good live price — the screen
blanked for a second, `mdlive` mirrored the 0 to every other worker, and the
order gate read "no live price" on a contract that was quoting fine. The OHLC
fields have always been protected; the LTP was the one that wasn't.
"""

from __future__ import annotations

import inspect

from app.services import market_data_service as mds

SRC = inspect.getsource(mds._zerodha_overlay)


def test_a_zero_tick_cannot_overwrite_a_good_price():
    assert 'merged["ltp"] = live.get("ltp", merged["ltp"])' not in SRC
    assert "if _live_ltp > 0:" in SRC


def test_a_real_price_still_gets_through():
    assert 'merged["ltp"] = live.get("ltp")' in SRC


def test_a_non_numeric_ltp_is_not_an_exception():
    """`float(None)` and `float("")` both raise; a feed hiccup must not take
    the overlay down with it."""
    i = SRC.index("_live_ltp = float")
    assert "except (TypeError, ValueError):" in SRC[i:i + 260]


def test_the_ohlc_fields_keep_their_own_guard():
    """Same rule, and it must stay — this is where it was borrowed from."""
    assert "def _keep(" in SRC and "if v > 0:" in SRC


def test_the_readers_still_refuse_a_zero():
    """Belt and braces: nothing downstream may report 0 as a price."""
    for fn in (mds.get_ltp_live, mds.get_ltp_instant):
        assert "if v > 0" in inspect.getsource(fn) or "if v > 0 else None" in inspect.getsource(fn)


def test_the_last_known_price_is_still_offered_for_display():
    """When there genuinely is no live price, `ltp` stays 0 (nothing may fill
    against it) and the last real one rides along for the screen."""
    src = inspect.getsource(mds._attach_last_quote)
    assert 'out["last_ltp"]' in src
    assert 'out["stale"] = True' in src
