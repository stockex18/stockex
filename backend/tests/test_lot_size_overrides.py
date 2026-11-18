"""Super-admin lot sizes (services/lot_overrides.py).

What has to hold:

  * a super-admin row wins over the coded tables, for index F&O, stock F&O,
    MCX, international symbols and BTC options;
  * it never leaks into equity cash (1 share = 1 lot) or into a different
    contract that merely starts with the same letters;
  * deleting the row brings the built-in value back;
  * a DB blip keeps the last good copy;
  * the admin routes are super-admin only and refuse bad input before
    touching the database.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.api.v1.admin import lot_sizes as routes
from app.core.exceptions import ValidationFailedError
from app.services import index_lots, infoway_lots
from app.services import lot_overrides as lo


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.setattr(lo, "_indian", {})
    monkeypatch.setattr(lo, "_international", {})
    monkeypatch.setattr(lo, "_loaded_at", 0.0)


def _run(c):
    return asyncio.run(c)


def test_index_fno_uses_the_super_admin_lot():
    assert index_lots.get_canonical_lot_size("NIFTY26NOV24000CE", "NIFTY", exchange="NFO", instrument_type="CE") == 65
    lo.set_local("INDIAN", "NIFTY", 75)
    assert index_lots.get_canonical_lot_size("NIFTY26NOV24000CE", "NIFTY", exchange="NFO", instrument_type="CE") == 75
    # BANKNIFTY / NIFTYNXT50 are other contracts, not NIFTY.
    assert index_lots.get_canonical_lot_size("BANKNIFTY26NOVFUT", None, exchange="NFO", instrument_type="FUT") == 30
    assert lo.indian_lot("NIFTYNXT5026NOVFUT") is None


def test_names_with_digits_can_be_set():
    lo.set_local("INDIAN", "NIFTYNXT50", 30)
    assert lo.indian_lot("NIFTYNXT5026NOV70000CE") == 30
    assert lo.indian_lot("NIFTYNXT50") == 30
    assert lo.indian_lot("NIFTYNXT26NOVFUT") is None
    assert lo.builtin_lot("INDIAN", "NIFTYNXT50") == 25


def test_stock_fno_gets_a_lot_only_when_the_super_admin_sets_one():
    args = ("RELIANCE26NOVFUT", "RELIANCE")
    assert index_lots.get_canonical_lot_size(*args, exchange="NFO", instrument_type="FUT") is None  # → CSV
    lo.set_local("INDIAN", "RELIANCE", 500)
    assert index_lots.get_canonical_lot_size(*args, exchange="NFO", instrument_type="FUT") == 500


def test_equity_cash_is_never_resized():
    lo.set_local("INDIAN", "RELIANCE", 500)
    assert index_lots.get_canonical_lot_size("RELIANCE", "RELIANCE", exchange="NSE", instrument_type="EQ") is None


def test_mcx_uses_the_super_admin_lot_and_keeps_roots_apart():
    lo.set_local("INDIAN", "GOLD", 50)
    assert index_lots.get_canonical_lot_size("GOLD26DECFUT", None, exchange="MCX", instrument_type="FUT") == 50
    assert index_lots.get_canonical_lot_size("GOLDM26DECFUT", None, exchange="MCX", instrument_type="FUT") == 10


def test_symbols_with_and_and_dash_keep_their_root():
    lo.set_local("INDIAN", "M&M", 350)
    assert lo.indian_lot("M&M26NOVFUT") == 350
    assert lo.indian_lot("MM26NOVFUT") is None


def test_international_and_btc_options_use_the_super_admin_lot():
    assert infoway_lots.get_infoway_lot_size("EURUSD", "FOREX") == 100000
    lo.set_local("INTERNATIONAL", "EURUSD", 1000)
    assert infoway_lots.get_infoway_lot_size("EURUSD", "FOREX") == 1000
    lo.set_local("INTERNATIONAL", "ETHUSD", 10)
    assert infoway_lots.get_infoway_lot_size("ETHUSDT", "CRYPTO") == 10
    assert infoway_lots.btc_option_lot_size("BTC-261127-90000-C", "CRYPTO_OPTIONS") == 1
    lo.set_local("INTERNATIONAL", "BTC", 5)
    assert infoway_lots.btc_option_lot_size("BTC-261127-90000-C", "CRYPTO_OPTIONS") == 5
    # BTC spot is BTCUSD, not BTC.
    assert infoway_lots.get_infoway_lot_size("BTCUSD", "CRYPTO") == 100


def test_deleting_brings_the_builtin_value_back():
    lo.set_local("INDIAN", "NIFTY", 75)
    lo.set_local("INDIAN", "NIFTY", None)
    assert index_lots.get_index_lot_size("NIFTY26NOVFUT") == 65


def test_builtin_lot_ignores_super_admin_rows():
    lo.set_local("INDIAN", "NIFTY", 75)
    assert lo.builtin_lot("INDIAN", "NIFTY") == 65
    assert lo.builtin_lot("INDIAN", "GOLDM") == 10
    assert lo.builtin_lot("INDIAN", "RELIANCE") is None
    assert lo.builtin_lot("INTERNATIONAL", "BTC") == 1
    assert lo.builtin_lot("INTERNATIONAL", "XAUUSD") == 100
    groups = {r["group"] for r in lo.builtin_table()}
    assert {"NSE / BSE index F&O", "MCX", "BTC options", "International"} <= groups


def _fake_model(monkeypatch, rows=None, fail=False):
    import app.models.lot_size_override as m

    class Q:
        async def to_list(self):
            if fail:
                raise RuntimeError("db down")
            return rows or []

    monkeypatch.setattr(m.LotSizeOverride, "find_all", classmethod(lambda cls: Q()))


def test_refresh_loads_rows_and_keeps_the_last_copy_on_a_db_blip(monkeypatch):
    _fake_model(monkeypatch, rows=[
        SimpleNamespace(market="INDIAN", underlying="NIFTY", lot_size=75),
        SimpleNamespace(market="INTERNATIONAL", underlying="EURUSD", lot_size=1000),
    ])
    _run(lo.refresh(max_age=0))
    assert lo.indian_lot("NIFTY26NOVFUT") == 75
    assert lo.international_lot("EURUSD") == 1000
    _fake_model(monkeypatch, fail=True)
    _run(lo.refresh(max_age=0))
    assert lo.indian_lot("NIFTY26NOVFUT") == 75


def test_refresh_is_skipped_while_fresh(monkeypatch):
    _fake_model(monkeypatch, rows=[SimpleNamespace(market="INDIAN", underlying="NIFTY", lot_size=75)])
    _run(lo.refresh(max_age=0))
    _fake_model(monkeypatch, rows=[])
    _run(lo.refresh())  # within MAX_AGE_SEC: no reload
    assert lo.indian_lot("NIFTY26NOVFUT") == 75


@pytest.mark.parametrize("body", [
    {"market": "MARS", "underlying": "NIFTY", "lot_size": 75},
    {"market": "INDIAN", "underlying": "50NIFTY", "lot_size": 75},
    {"market": "INDIAN", "underlying": "", "lot_size": 75},
    {"market": "INDIAN", "underlying": "NIFTY", "lot_size": 0},
    {"market": "INDIAN", "underlying": "NIFTY", "lot_size": -5},
    {"market": "INTERNATIONAL", "underlying": "EUR/USD", "lot_size": 1000},
])
def test_bad_input_is_refused_before_the_database(body, monkeypatch):
    import app.models.lot_size_override as m

    async def no_db(*a, **k):
        raise AssertionError("database touched")

    monkeypatch.setattr(m.LotSizeOverride, "find_one", no_db)
    with pytest.raises(ValidationFailedError):
        _run(routes.set_lot_size(routes.LotSizeIn(**body), SimpleNamespace(id=None)))


def test_routes_are_super_admin_only_and_mounted():
    for fn in (routes.list_lot_sizes, routes.set_lot_size, routes.delete_lot_size):
        assert "admin: SuperAdmin" in inspect.getsource(fn)
    import app.main as main

    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/v1/admin/lot-sizes" in paths
    assert "/api/v1/admin/lot-sizes/{row_id}" in paths


def test_order_placement_refreshes_and_asks_the_super_admin_lot_first():
    from app.services import order_service

    src = inspect.getsource(order_service)
    assert "await lot_overrides.refresh()" in src
    assert "lot_overrides.indian_lot(instrument.symbol, instrument.name)" in src
