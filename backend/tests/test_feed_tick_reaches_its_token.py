"""A crypto tick has to arrive under the token the browser asked for.

Screenshot from the terminal: the BTCUSD chart live at 85,273.54, the order
panel quoting SELL 85,253.54 / BUY 85,293.54 — and the instruments panel
beside them showing "—" for every crypto row, BTCUSD included. Same page,
same symbol, same second.

The chart and the order panel read the quote endpoint. The instruments
panel reads the live WebSocket. So the quote path worked and the stream
path did not.

Listening on the live channel settled it. The feed publishes:

    infoway:tick:BTCUSDT   {"symbol": "BTCUSDT", "ltp": 85264.75, ...}
    token: None

`MarketTickHub` routes on `payload["token"] or payload["symbol"]`, so that
tick was filed under "BTCUSDT". The browser subscribes with the instrument
token, "CRYPTO_BTCUSD", and keys its price map off `payload.token`. The two
never met: nobody was listening on "BTCUSDT", and had the frame arrived it
would have carried a token the client could not match to any row.

134 channels were publishing in a 15-second window at the time, all six spot
pairs among them. The data was always there. It was filed under a name
nothing answered to.
"""

from __future__ import annotations

import inspect

import pytest

from app.core.ws_hub import MarketTickHub, market_tick_hub
from app.services import market_data_service as mds


@pytest.fixture
def mapped(monkeypatch):
    """One crypto instrument in the reverse map, as the boot warm would."""
    monkeypatch.setattr(mds, "_symbol_token_cache", {}, raising=False)
    mds._index_symbol_token("CRYPTO_BTCUSD", "BTCUSD")
    return mds


# ── the reverse map ───────────────────────────────────────────────────
def test_a_usdt_pair_resolves_to_our_token(mapped):
    """Binance quotes a USD pair as USDT — the same convention the quote
    overlay already leans on when it tries `sym` then `sym + "T"`."""
    assert mds.token_for_feed_symbol("BTCUSDT") == "CRYPTO_BTCUSD"


def test_the_plain_symbol_resolves_too(mapped):
    assert mds.token_for_feed_symbol("BTCUSD") == "CRYPTO_BTCUSD"


def test_case_does_not_matter(mapped):
    assert mds.token_for_feed_symbol("btcusdt") == "CRYPTO_BTCUSD"


def test_an_unknown_symbol_resolves_to_nothing(mapped):
    assert mds.token_for_feed_symbol("NOSUCHPAIR") is None
    assert mds.token_for_feed_symbol(None) is None


def test_zerodha_instruments_are_kept_out_of_the_map():
    """Their ticks already carry a token, so they never need resolving
    backwards — and indexing them would let a name like RELIANCE shadow a
    feed symbol."""
    mds._symbol_token_cache.clear()
    mds._index_symbol_token("256265", "RELIANCE")
    assert mds.token_for_feed_symbol("RELIANCE") is None


def test_the_lookup_stays_synchronous():
    """It runs for every tick on the fan-out path. An await here would put a
    Mongo round-trip between the feed and the screen."""
    assert not inspect.iscoroutinefunction(mds.token_for_feed_symbol)


# ── what the hub does with it ─────────────────────────────────────────
def test_a_feed_tick_is_routed_under_our_token(mapped):
    payload = {"symbol": "BTCUSDT", "ltp": 85264.75}
    keys = market_tick_hub._route_keys("infoway:tick:BTCUSDT", payload)
    assert "CRYPTO_BTCUSD" in keys


def test_the_frame_carries_the_token_the_client_subscribed_with(mapped):
    """The browser keys its price map off `payload.token`. A frame labelled
    BTCUSDT matches no row, which is the dash."""
    payload = {"symbol": "BTCUSDT", "ltp": 85264.75}
    market_tick_hub._route_keys("infoway:tick:BTCUSDT", payload)
    assert payload["token"] == "CRYPTO_BTCUSD"


def test_the_raw_symbol_is_still_routed(mapped):
    """Anything already listening on the feed symbol keeps working."""
    keys = market_tick_hub._route_keys("infoway:tick:BTCUSDT", {"symbol": "BTCUSDT"})
    assert "BTCUSDT" in keys


def test_an_untranslatable_symbol_behaves_exactly_as_before(mapped):
    payload = {"symbol": "WHATEVER", "ltp": 1.0}
    keys = market_tick_hub._route_keys("infoway:tick:WHATEVER", payload)
    assert keys == ["WHATEVER"]
    assert payload["token"] == "WHATEVER"


def test_a_tick_that_already_names_a_token_is_untouched(mapped):
    """Zerodha publishes its own token; nothing should be re-resolved."""
    payload = {"token": "256265", "ltp": 100.0}
    keys = market_tick_hub._route_keys("market:tick:256265", payload)
    assert keys == ["256265"]
    assert payload["token"] == "256265"


def test_a_payload_that_names_nothing_is_dropped(mapped):
    assert market_tick_hub._route_keys("infoway:tick:X", {"ltp": 1}) == []
    assert market_tick_hub._route_keys("infoway:tick:X", "not a dict") == []


def test_the_translation_lives_in_the_market_hub_only():
    """The user and admin hubs route their own keys and must not pay for
    an instrument lookup."""
    assert "token_for_feed_symbol" in inspect.getsource(MarketTickHub._route_keys)
