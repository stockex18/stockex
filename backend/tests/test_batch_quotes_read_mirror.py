"""A batch quote must be as live as a single one.

Reported: "terminal kholte hi side favourite list me rate 10-20 second baad
dikhta hai", and the same again after being away ten minutes.

Measured first, because the obvious suspects were all innocent:

    /marketwatch/{id}/quotes handler, 32 items      5 ms
    get_quotes(32) cold                            29 ms
    /health over loopback                           1-3 ms
    /health through nginx + TLS                    30-100 ms
    watchlist tokens already subscribed            54 of 68
                                                   (the 14 misses are crypto,
                                                    a different feed)

Nothing there is slow. The problem is that `get_quotes` was not returning a
live price at all on most requests.

Only the LEADER worker runs the feed loops, so on every other worker `_state`
is permanently cold — the comment on `_MDLIVE_KEY` says so, and `get_quote`
(singular) short-circuits on the `mdlive` mirror for exactly that reason.
`get_quotes` (plural) never learned to. It went straight to `_overlay_all`,
got nothing, and `_attach_last_quote` filled in the last SESSION's price.

Production runs 5 gunicorn workers. Four requests in five were answered with no
live rate, so the screen had nothing to show until a websocket tick arrived —
and both REST calls the terminal makes on open go through this one function:
the favourite list's `/marketwatch/{id}/quotes` and the panel's
`/instruments/quotes-batch`.

`get_quote_batch_mdlive` already existed and was already one MGET. It just was
not wired here.
"""

from __future__ import annotations

import inspect

from app.services import market_data_service as mds

SRC = inspect.getsource(mds.get_quotes)


def test_the_batch_reads_the_leaders_mirror_first():
    assert "mirror = await get_quote_batch_mdlive(tokens)" in SRC
    assert SRC.index("get_quote_batch_mdlive") < SRC.index("_ensure_quote")


def test_a_mirror_hit_skips_the_cold_path_entirely():
    """The whole point — a cold worker must not fall through to `_overlay_all`
    and answer with a previous session's close."""
    i = SRC.index("live = mirror.get(t)")
    block = SRC[i : i + 260]
    assert "if live:" in block
    assert "return out" in block
    assert block.index("return out") < block.index("_ensure_quote") if "_ensure_quote" in block else True


def test_a_miss_still_takes_the_full_path():
    """Tokens the mirror does not hold — a fresh subscription, an Infoway
    symbol — must still resolve, and still get their last-quote fallback."""
    assert "q = await _ensure_quote(t)" in SRC
    assert "_overlay_all(t, q, allow_rest=False)" in SRC
    assert "_attach_last_quote(t, out)" in SRC


def test_it_is_one_mget_for_the_whole_batch_not_one_per_token():
    """Per-token reads would put the round trips back. The mirror is fetched
    once, outside the gather."""
    assert SRC.index("mirror = await") < SRC.index("async def _one")
    assert SRC.count("get_quote_batch_mdlive") == 1


def test_the_parallel_fan_out_survives():
    """The earlier fix this function already carried: serial overlays were a
    ~10 s worst case for five instruments."""
    assert "asyncio.gather(*[_one(t) for t in tokens])" in SRC


def test_rest_is_still_never_issued_from_this_path():
    """`allow_rest=True` here would be a ~2 s Kite call per cold token, which
    is the thing the fan-out was written to escape in the first place."""
    assert "allow_rest=False" in SRC
    assert "allow_rest=True" not in SRC


def test_a_mirror_quote_is_stamped_for_freshness_like_the_single_reader():
    """`get_quote` marks its mdlive hit before returning; a batch hit that
    skipped it would report as fresh forever."""
    assert "_mark_freshness(dict(live))" in SRC
    assert 'out["ts"] = now_ms' in SRC
    assert "_mark_freshness(dict(live))" in inspect.getsource(mds.get_quote)


def test_the_singular_reader_still_short_circuits_too():
    """Both readers have to agree, or the same token reads live one way and
    stale the other."""
    src = inspect.getsource(mds.get_quote)
    assert "live = await _read_mdlive(token)" in src


def test_the_mirror_reader_ignores_a_zero_price():
    """A mirrored entry with ltp 0 is not a usable quote; treating it as a hit
    would serve zeros and skip the fallback that has a real number."""
    assert 'float(data.get("ltp") or 0) > 0' in inspect.getsource(mds.get_quote_batch_mdlive)


def test_both_terminal_endpoints_go_through_this_function():
    """If either ever grows its own copy, the fix stops covering it.

    They call the DISPLAY wrapper now, which is a thin shell over `get_quotes`
    that fills in the last print instead of rendering 0 after the close — so
    the mirror read this file is about still happens underneath.
    """
    from app.api.v1.user import instruments as inst_api
    from app.api.v1.user import marketwatch as mw_api

    assert "get_display_quotes(" in inspect.getsource(mw_api.quotes)
    assert "get_display_quotes(" in inspect.getsource(inst_api)
    assert "await get_quotes(tokens)" in inspect.getsource(mds.get_display_quotes)
