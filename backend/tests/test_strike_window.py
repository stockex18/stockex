"""ATM strike-window gate — the close-only rule for out-of-window strikes.

Guards the regression this replaced: both option strike gates resolved the
underlying via ``Instrument.underlying_token``, which is NULL on every option
mirrored from the Zerodha CSV, so the lookup returned None and the gates
silently no-op'd — a strike that had dropped out of the chain window (gone
from search AND from the picker) could still be added to from the Positions
tab.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from bson import Decimal128

from app.api.v1.user import option_chain as oc
from app.services.order_validator import _underlying_root, strike_window_breach

EXPIRY = date(2026, 8, 11)


def _instrument(strike: float, symbol: str = "NIFTY2681124900CE", expiry=EXPIRY):
    return SimpleNamespace(symbol=symbol, expiry=expiry, strike=Decimal128(str(strike)))


def _ladder(lo: int, hi: int, step: int, expiry=EXPIRY):
    """Catalog rows the way `get_option_chain_fast` returns them."""
    return [
        {"strike": float(k), "option_type": "CE", "_expiry_date": expiry}
        for k in range(lo, hi + 1, step)
    ]


def _patch(monkeypatch, *, window: int, spot: float | None, rows=None):
    async def _fake_window(_seg_key):
        return window

    async def _fake_catalog(_und):
        return (rows if rows is not None else _ladder(24000, 25000, 50), [])

    async def _fake_spot(_und, _exchange=None):
        return spot

    monkeypatch.setattr(oc, "_strikes_around_atm_for", _fake_window)
    monkeypatch.setattr(oc, "_cached_catalog", _fake_catalog)
    monkeypatch.setattr(oc, "_underlying_spot", _fake_spot)


def test_underlying_root():
    assert _underlying_root("NIFTY2681124900CE") == "NIFTY"
    assert _underlying_root("BANKNIFTY25AUG54000PE") == "BANKNIFTY"
    assert _underlying_root("CRUDEOIL25AUG5800CE") == "CRUDEOIL"
    assert _underlying_root(None) == ""


async def test_far_strike_is_out_of_window(monkeypatch):
    # spot 24500 → ATM 24500; 24900 is 8 ladder steps away, window is 3.
    _patch(monkeypatch, window=3, spot=24500.0)
    assert await strike_window_breach(_instrument(24900), "NSE") == 3


async def test_near_strike_is_inside_window(monkeypatch):
    # spot 24850 → ATM 24850; 24900 is 1 ladder step away.
    _patch(monkeypatch, window=3, spot=24850.0)
    assert await strike_window_breach(_instrument(24900), "NSE") is None


async def test_edge_of_window_allowed(monkeypatch):
    # spot 24750 → ATM 24750; 24900 is exactly 3 steps — the window is inclusive.
    _patch(monkeypatch, window=3, spot=24750.0)
    assert await strike_window_breach(_instrument(24900), "NSE") is None


async def test_fails_open_without_spot(monkeypatch):
    """A feed gap must never block a legitimate order."""
    _patch(monkeypatch, window=3, spot=None)
    assert await strike_window_breach(_instrument(24900), "NSE") is None


async def test_fails_open_on_cold_catalog(monkeypatch):
    _patch(monkeypatch, window=3, spot=24500.0, rows=[])
    assert await strike_window_breach(_instrument(24900), "NSE") is None


async def test_window_disabled_lets_everything_through(monkeypatch):
    _patch(monkeypatch, window=0, spot=24500.0)
    assert await strike_window_breach(_instrument(24900), "NSE") is None


async def test_short_ladder_never_blocks(monkeypatch):
    """Ladder smaller than the window itself — nothing can be outside it."""
    _patch(monkeypatch, window=3, spot=24500.0, rows=_ladder(24400, 24600, 50))
    assert await strike_window_breach(_instrument(24600), "NSE") is None


async def test_missing_expiry_fails_open(monkeypatch):
    _patch(monkeypatch, window=3, spot=24500.0)
    assert await strike_window_breach(_instrument(24900, expiry=None), "NSE") is None


async def test_short_ladder_off_centre_atm_still_trims(monkeypatch):
    """COPPER: 39 strikes ≤ 2×20+1, but ATM is 14th from the bottom, so the
    top of the ladder is more than 20 strikes away and must be outside."""
    _patch(monkeypatch, window=20, spot=1336.0, rows=_ladder(1210, 1590, 10))
    allowed, _ = await oc.allowed_strike_set("COPPER", EXPIRY, "MCX")
    assert allowed is not None
    assert max(allowed) == 1540.0 and min(allowed) == 1210.0
    assert 1550.0 not in allowed


async def test_strike_far_trims_like_the_chain(monkeypatch):
    _patch(monkeypatch, window=20, spot=1336.0, rows=_ladder(1210, 1590, 10))

    async def _far(_exchange):
        return 10.0  # ±10% of 1336 → 1202.4 … 1469.6

    monkeypatch.setattr(oc, "_strike_far_pct_for", _far)
    allowed, _ = await oc.allowed_strike_set("COPPER", EXPIRY, "MCX", strike_far=True)
    assert max(allowed) == 1460.0
    # The order gate does not ask for it — that cap is enforced per user there.
    allowed_no_far, _ = await oc.allowed_strike_set("COPPER", EXPIRY, "MCX")
    assert max(allowed_no_far) == 1540.0


async def test_mcx_spot_prefers_the_mcx_future(monkeypatch):
    """SILVER is also an NSE ETF (~186); MCX must price off its future."""
    from app.services import zerodha_service

    async def _find(_sym):
        return {"symbol": "SILVER", "exchange": "NSE", "token": 1}

    async def _fut(_root, exchanges=("MCX", "NFO", "BFO")):
        return 2 if exchanges == ("MCX",) else None

    async def _price(tok):
        return {1: 186.25, 2: 183100.0}[int(tok)]

    monkeypatch.setattr(zerodha_service.zerodha, "find_instrument_by_symbol", _find)
    monkeypatch.setattr(oc, "_nearest_future_token", _fut)
    monkeypatch.setattr(oc, "_price_for_token", _price)
    assert await oc._underlying_spot("SILVER", "MCX") == 183100.0
    assert await oc._underlying_spot("SILVER") == 186.25  # non-MCX callers unchanged
