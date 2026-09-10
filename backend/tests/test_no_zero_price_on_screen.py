"""A favourite sat at 0.00 / 0.00 while the last price was right there.

Reported on HEG-BE after the close. Measured on the live box:

    mdlive:1886209  -> None            (30 s TTL, expired)
    mdlast:1886209  -> ltp 249.65      (7-day TTL, good)
    quotes/batch    -> ltp 0.0, bid 0.0, ask 0.0, last_ltp 249.65, stale True

`_attach_last_quote` leaves ltp / bid / ask at 0 on purpose and hands the
price over as a separate `last_ltp`, because an execution path reading a stale
number as if it were live is the one thing that must never happen. Every
screen then rendered those zeros.

Operator: "0 kabhi na dikhe kisi me, LTP dikhe". So the fill is applied at
every DISPLAY read — batch quotes, single quote, both marketwatches, the
option chain, the public page and the websocket fan-out. The websocket one
matters most: without it a tick would push 0 straight back over whatever REST
had just filled in.

`get_quote` / `get_quotes` are left alone, so anything that ever needs to
trade off them still sees the truth, and `stale` stays True either way — the
row is showing a last print, not a live rate.
"""

from __future__ import annotations

import inspect

from app.services import market_data_service as mds


def test_a_dead_quote_shows_the_last_print():
    q = mds.fill_display_price(
        {"ltp": 0.0, "bid": 0.0, "ask": 0.0, "last_ltp": 249.65, "stale": True}
    )
    assert q["ltp"] == 249.65
    assert q["bid"] == 249.65
    assert q["ask"] == 249.65


def test_it_still_says_the_row_is_stale():
    # The number is a last print, not a live rate, and the UI has to know.
    q = mds.fill_display_price({"ltp": 0.0, "last_ltp": 249.65, "stale": True})
    assert q["stale"] is True


def test_a_live_quote_is_returned_untouched():
    live = {"ltp": 250.10, "bid": 250.05, "ask": 250.15, "last_ltp": 249.65}
    assert mds.fill_display_price(live) is live


def test_a_real_bid_or_ask_is_not_overwritten():
    q = mds.fill_display_price({"ltp": 0.0, "bid": 249.60, "ask": 0.0, "last_ltp": 249.65})
    assert q["bid"] == 249.60  # kept
    assert q["ask"] == 249.65  # filled


def test_nothing_known_stays_zero():
    # Inventing a price would be worse than showing none.
    q = mds.fill_display_price({"ltp": 0.0, "bid": 0.0, "ask": 0.0, "last_ltp": 0.0})
    assert q["ltp"] == 0.0
    q2 = mds.fill_display_price({"ltp": 0.0})
    assert float(q2.get("ltp") or 0) == 0.0


def test_a_junk_value_does_not_raise():
    # These rows come off a cache; one bad field must not break a whole batch.
    assert mds.fill_display_price({"ltp": "x", "last_ltp": "y"}) is not None
    assert mds.fill_display_price({}) == {}


# ── every display read goes through it ──────────────────────────────────────

def test_the_display_wrappers_use_the_shared_filler():
    assert "fill_display_price(await get_quote(token))" in inspect.getsource(
        mds.get_display_quote
    )
    assert "fill_display_price(q) for q in await get_quotes(tokens)" in inspect.getsource(
        mds.get_display_quotes
    )


def test_execution_reads_are_left_honest():
    for fn in (mds.get_quote, mds.get_quotes):
        assert "fill_display_price" not in inspect.getsource(fn)


def test_every_screen_endpoint_switched():
    import app.api.v1.market_public as pub
    import app.api.v1.admin.instruments as adm_inst
    import app.api.v1.admin.marketwatch as adm_mw
    import app.api.v1.user.instruments as u_inst
    import app.api.v1.user.marketwatch as u_mw
    import app.api.v1.user.option_chain as chain

    for mod in (pub, adm_inst, adm_mw, u_inst, u_mw, chain):
        src = inspect.getsource(mod)
        assert "get_display_quote" in src, mod.__name__


def test_the_websocket_fan_out_switched_too():
    # Without this a tick pushes 0 back over whatever REST just filled in,
    # and the price blinks away a second after the page loads.
    import app.api.ws.market_ws as ws

    src = inspect.getsource(ws)
    assert src.count("market_data_service.get_display_quote(") == 2
    assert "market_data_service.get_quote(" not in src


def test_the_bracket_watermark_still_reads_the_raw_quote():
    # It is a GATE — it stamps the day range an SL/TP is judged against, and a
    # week-old high/low must not decide whether a stop fires.
    import app.api.v1.user.positions as pos

    assert "_m.get_quote(p.instrument.token)" in inspect.getsource(pos)
