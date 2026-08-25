"""Parked orders fire at feed speed, not at tick-loop speed.

The poller read `_state`, which `tick_loop` refreshes once a SECOND, so a LIMIT
could sit up to a second past its price before firing — and polling more often
would only re-read the same stale number. The scan was never the cost: measured
0.8 ms against an index on production.

The trap this guards: reading the raw websocket walks straight past the
super-admin's market-control freeze, because crypto and forex keep streaming
through a closure. A frozen token must keep serving its HELD price.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.services import market_data_service as mds
from app.services import matching_engine


class _WS:
    """Stand-in for the Zerodha websocket tick cache."""

    def __init__(self, ticks):
        self.ticks_by_token = ticks


@pytest.fixture(autouse=True)
def _clean():
    before = set(mds._frozen_tokens)
    mds._frozen_tokens = set()
    yield
    mds._frozen_tokens = before


def _wire(monkeypatch, *, ws_ltp=None, state_ltp=None):
    import sys

    mod = type(sys)("app.services.zerodha_service")
    mod.zerodha = _WS({1234: {"ltp": ws_ltp}} if ws_ltp is not None else {})
    monkeypatch.setitem(sys.modules, "app.services.zerodha_service", mod)
    monkeypatch.setattr(
        mds, "_state", {"1234": {"ltp": state_ltp}} if state_ltp is not None else {}
    )


# -- the live read ----------------------------------------------------
def test_the_websocket_tick_beats_the_one_second_snapshot(monkeypatch):
    _wire(monkeypatch, ws_ltp="101.5", state_ltp="100.0")
    assert mds.get_ltp_live("1234") == D("101.5")


def test_it_falls_back_to_the_snapshot_when_there_is_no_tick(monkeypatch):
    _wire(monkeypatch, state_ltp="100.0")
    assert mds.get_ltp_live("1234") == D("100.0")


def test_a_zero_tick_is_not_a_price(monkeypatch):
    """A 0 from the feed means "no price yet", not "worth nothing"."""
    _wire(monkeypatch, ws_ltp="0", state_ltp="100.0")
    assert mds.get_ltp_live("1234") == D("100.0")


def test_nothing_anywhere_reads_none(monkeypatch):
    _wire(monkeypatch)
    assert mds.get_ltp_live("1234") is None


# -- the freeze -------------------------------------------------------
def test_a_frozen_token_holds_its_price(monkeypatch):
    """Crypto and forex stream through a market-control closure. Reading the
    websocket there would fire orders in a segment the operator has shut."""
    _wire(monkeypatch, ws_ltp="101.5", state_ltp="100.0")
    mds._frozen_tokens = {"1234"}
    assert mds.get_ltp_live("1234") == D("100.0")


def test_unfreezing_puts_the_live_price_back(monkeypatch):
    _wire(monkeypatch, ws_ltp="101.5", state_ltp="100.0")
    mds._frozen_tokens = {"1234"}
    assert mds.get_ltp_live("1234") == D("100.0")
    mds._frozen_tokens = set()
    assert mds.get_ltp_live("1234") == D("101.5")


def test_the_freeze_is_published_in_one_assignment():
    """A reader must never see a half-built set."""
    src = inspect.getsource(mds.tick_loop)
    assert "_frozen_now: set[str] = set()" in src
    assert "_frozen_tokens = _frozen_now" in src
    assert "_frozen_now.add(token)" in src


# -- the poller -------------------------------------------------------
def test_the_poller_reads_live_not_the_snapshot():
    src = inspect.getsource(matching_engine.trigger_pending_orders)
    assert "get_ltp_live(tok)" in src
    assert "get_ltp_instant(tok)" not in src


def test_the_poller_runs_ten_times_a_second():
    assert (
        inspect.signature(matching_engine.pending_order_poller)
        .parameters["interval_sec"].default == 0.1
    )


def test_the_lifespan_starts_it_at_that_interval():
    """The default is not what runs — main.py passes its own."""
    import io

    src = io.open(
        r"D:\stockex_new\backend\app\main.py", encoding="utf-8", errors="ignore"
    ).read()
    assert "_partial(pending_order_poller, interval_sec=0.1)" in src


def test_the_fill_price_contract_is_untouched():
    """Firing sooner is only safe because a LIMIT books at the USER's price,
    not at whatever the poller happened to read."""
    src = inspect.getsource(matching_engine.trigger_pending_orders)
    assert "expected_price" in src
