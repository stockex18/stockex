"""A tick found by NAME must still belong to the token asking for it.

Reported: NIFTY suddenly showed BANKNIFTY's rate.

The overlay has two fallbacks that resolve a price by SYMBOL — a symbol-keyed
tick cache, and a REST snapshot fetched by symbol. A name is not unique in this
catalog: twelve symbols are owned by three tokens each.

    BAJFINANCE  ->  81153  ·  128008708  ·  NSE_EQ_BAJFINANCE
    NTPC        ->  2977281  ·  136334084  ·  NSE_EQ_NTPC

`ticks_by_symbol` keeps one entry per name, so whichever of those ticks last
owns it — and the other two are then served its price. That is a wrong rate
that appears and disappears with nothing changing, which is exactly the shape
of the report.

I could not reproduce the specific NIFTY/BANKNIFTY case: both read correctly
now and neither is in the colliding set. What is fixed here is the mechanism.
"""

from __future__ import annotations

import inspect

from app.services import market_data_service as mds

SRC = inspect.getsource(mds._zerodha_overlay)


def test_a_symbol_keyed_tick_is_checked_against_the_token():
    assert "_cand = zerodha.ticks_by_symbol.get(sym)" in SRC
    assert 'str(_cand.get("token") or "") == str(token)' in SRC


def test_a_rest_snapshot_is_checked_too():
    """It is fetched BY SYMBOL, so it is only this token's price if the symbol
    resolved really belongs to this token."""
    assert 'str(snap.get("token") or "") in ("", "0", str(token))' in SRC


def test_synthetic_tokens_keep_the_fallback():
    """`NSE_EQ_RELIANCE` is exactly what the symbol fallback exists for and can
    never match a numeric Kite token. Requiring a match would switch the
    fallback off for the instruments that need it most."""
    assert SRC.count('str(token).lstrip("-").isdigit()') == 2
    assert SRC.count("if not _mine or") == 2


def test_a_mismatch_is_logged_loudly():
    """A price silently swapped between instruments is the worst kind of
    wrong. If this ever fires there has to be a record naming both sides."""
    for name in ("symbol_tick_token_mismatch", "rest_snapshot_token_mismatch"):
        i = SRC.index(name)
        assert "logger.warning" in SRC[i - 120 : i]
    assert '"tick_token"' in SRC
    assert '"snap_token"' in SRC


def test_a_mismatch_falls_back_rather_than_serving_the_wrong_price():
    """`live` stays None, so the overlay returns the base quote — a stale or
    empty price for the right instrument, never a live price for the wrong
    one."""
    i = SRC.index("symbol_tick_token_mismatch")
    block = SRC[i - 400 : i]
    assert "live = _cand" in block
    # the assignment is inside the matching branch, not before the check
    assert block.index("if not _mine or") < block.index("live = _cand")


def test_the_direct_token_lookup_is_still_tried_first():
    """It cannot be wrong — it is keyed by the token itself. The fallbacks
    only run when it misses."""
    assert "live = zerodha.ticks_by_token.get(int(token))" in SRC
    assert SRC.index("ticks_by_token.get(int(token))") < SRC.index("ticks_by_symbol.get(sym)")
