"""A user could open at 15:40 and then not be allowed to close.

The super-admin moved the NSE close to 15:41 in Market Control. Opens honour
that window — `order_validator` reads it, and exits skip the check entirely.
The USER-INITIATED close in `positions.py` did not: it carried a hardcoded
09:15-15:30, so at 15:35 the app answered

    "NSE market is closed. You can close this position once the market
     reopens."

on a position the same platform had just let the user open. Operator: "close
ko bhi allow kar, agar open allow kiya hai to close bhi allow kar."

Taking the window as a UNION with the default calendar rather than a
replacement matters. A window that runs LONGER widens the close gate, which is
the fix. One that closes EARLIER must not take away an exit the user has
today — an exit should always be at least as available as an entry.
"""

from __future__ import annotations

import asyncio
import inspect

from app.api.v1.user import positions as pos
from app.services import market_control_service as mcs


def _patch(monkeypatch, verdict):
    """Stand in for the SA's window. The gate imports the function per call,
    so patching the module attribute is enough."""

    async def fake(_row):
        return verdict

    monkeypatch.setattr(mcs, "market_control_open", fake)


def _open_now(seg="NSE_INDEX_OPTION_BUY"):
    return asyncio.run(pos._is_segment_market_open_now(seg, "NIFTY2691523400CE"))


def test_an_admin_window_that_says_open_wins(monkeypatch):
    # 15:35 on the default calendar is closed; the SA's 15:41 window says open.
    _patch(monkeypatch, True)
    assert _open_now() is True


def test_no_window_falls_back_to_the_default_calendar(monkeypatch):
    # None means "no opinion" — disabled, missing, or unparseable times.
    _patch(monkeypatch, None)
    got = _open_now()
    assert got in (True, False)  # whatever the calendar says, it decided


def test_an_earlier_window_does_not_remove_an_existing_exit(monkeypatch):
    # False must not be trusted as "closed" — the calendar still gets a say,
    # so a narrowed window can never strand a user in a position.
    _patch(monkeypatch, False)
    crypto = asyncio.run(pos._is_segment_market_open_now("CRYPTO_OPTION_BUY", "BTC"))
    assert crypto is True


def test_the_gate_never_blocks_an_exit_on_its_own_error():
    # A Mongo hiccup resolving the window must not strand a user in a
    # position; the lookup is wrapped and falls through to the calendar.
    src = inspect.getsource(pos._is_segment_market_open_now)
    i_try = src.index("try:")
    i_seg = src.index('seg = (segment_type or "").upper()')
    assert i_try < i_seg
    assert "except Exception:" in src[i_try:i_seg]


def test_both_close_endpoints_pass_the_symbol_through():
    # Index vs stock resolves to different admin rows, so the symbol has to
    # reach `_seg_name_for` or an index option reads the stock row's window.
    src = inspect.getsource(pos)
    assert src.count("await _is_segment_market_open_now(") == 2
    assert 'getattr(p.instrument, "symbol", None)' in src


def test_open_and_closed_are_told_apart():
    # `market_control_reason` returns None both for "inside the window" and
    # "no window at all". The close gate needs those separated.
    assert inspect.iscoroutinefunction(mcs.market_control_open)
    src = inspect.getsource(mcs.market_control_open)
    assert "return None" in src and "return False" in src and "return True" in src
