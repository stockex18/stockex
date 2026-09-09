"""LTP vanished from the positions page and M2M read 0.00.

Measured on the live box after the close, on the token behind an open NIFTY
option position:

    mdlive:12107010   -> None      (30 s TTL, expired)
    mdlast:12107010   -> 168.65    (7-day TTL, good)
    get_quote         -> ltp 0.0, last_ltp 168.65, stale True
    get_ltp           -> 0.00

The positions page marks each row with `get_ltp`, so a 0 made every card fall
back to its own entry price: LTP printed as the entry and M2M as 0.00.

And it flickers, which is what the operator actually noticed - "0 ho raha hai
phir wapas aa raha hai". Only the worker holding `leader:feed` keeps a warm
in-process `_state`; on the other four `mdlive` has expired. Consecutive polls
land on different workers, so the price appears and disappears.

`get_ltp` returning 0 is CORRECT for execution - filling against a stale print
is the one thing that must never happen, and there is a whole
ALLOW_TRADE_AT_LAST_PRICE gate around that decision. So the fix is a separate
display-only read, not a change to the execution one. Gates keep using
`get_ltp`: the hold-time guard, the bracket-direction check and the
square-off-all market check all decide something, and a week-old price must
not decide anything.
"""

from __future__ import annotations

import asyncio
import inspect

from app.services import market_data_service as mds
from app.api.v1.user import positions as pos


def _quote(monkeypatch, **row):
    async def fake(_tok):
        return row

    monkeypatch.setattr(mds, "get_quote", fake)


def test_a_live_price_is_used_as_is(monkeypatch):
    _quote(monkeypatch, ltp=177.5, last_ltp=168.65)
    assert float(asyncio.run(mds.get_display_ltp("1"))) == 177.5


def test_it_falls_back_to_the_last_print(monkeypatch):
    # The measured shape: no live price, mdlast still holding one.
    _quote(monkeypatch, ltp=0.0, last_ltp=168.65, stale=True)
    assert float(asyncio.run(mds.get_display_ltp("1"))) == 168.65


def test_nothing_anywhere_still_reads_zero(monkeypatch):
    # No price at all must stay 0 so the caller's own zero-guard fires,
    # rather than inventing a number.
    _quote(monkeypatch, ltp=0.0, last_ltp=0.0)
    assert float(asyncio.run(mds.get_display_ltp("1"))) == 0.0
    _quote(monkeypatch, ltp=0.0)
    assert float(asyncio.run(mds.get_display_ltp("1"))) == 0.0


def test_execution_still_refuses_a_stale_price(monkeypatch):
    # get_ltp must NOT gain the fallback — that is the whole point of keeping
    # two reads.
    _quote(monkeypatch, ltp=0.0, last_ltp=168.65)
    assert float(asyncio.run(mds.get_ltp("1"))) == 0.0


def test_the_screens_use_the_display_read():
    src = inspect.getsource(pos)
    # positions list, position detail, blotter, pnl-summary, holdings
    assert src.count("get_display_ltp(") == 5


def test_the_gates_do_not():
    # Each of these decides something; a week-old price must not decide it.
    src = inspect.getsource(pos)
    for gate in (
        "Hold-time guard",          # close path
        "bracket_direction_error",  # SL/TP direction
    ):
        assert gate in src
    # Three left: hold-time guard, bracket-direction check, square-off-all.
    assert src.count("market_data_service.get_ltp(") == 3
    assert src.count("_mds.get_ltp(") == 0
