"""Portfolio-level partial auto square at carry-forward, on the operator's own numbers.

Five MCX positions of ~1 crore each, intraday 100x, wallet 5,00,000:

    price       qty        carry_x   carry margin
    Silver  2,35,000   42.55        25x      4.00 L
    Copper      1,380  7,246.3      22x      4.54 L
    Crude       8,150  1,227        20x      5.00 L
    Zinc          417  23,980       18x      5.55 L
    Gold    1,55,000   64.51        40x      2.50 L
                                             ------
                                             21.59 L needed, 5 L available

Shortfall 16.59 L, squared FIRST-IN-FIRST: Silver + Copper + Crude whole
(13.54 L), then Zinc partially for the remaining 3.05 L. Gold — the newest —
carries untouched, even though its margin is the smallest.

Close P&L moves `available`, so it moves only the boundary position:
    -1,00,000 -> ~4,316 MORE Zinc squared
    +2,00,000 -> ~8,632 LESS Zinc squared

These drive the REAL `_fifo_carry_plan`, not a model of it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.services import position_service as ps

T0 = datetime(2026, 9, 1, 4, 0, 0)

#: name, price, qty, carry leverage — listed in ENTRY order.
BOOK = [
    ("Silver", D("235000"), D("42.55"), 25),
    ("Copper", D("1380"), D("7246.3"), 22),
    ("Crude", D("8150"), D("1227"), 20),
    ("Zinc", D("417"), D("23980"), 18),
    ("Gold", D("155000"), D("64.51"), 40),
]
USER = "u1"


class _Inst:
    def __init__(self, name):
        self.symbol = name.upper() + "26SEPFUT"
        self.segment = "MCX_FUT"
        self.lot_size = 1
        self.token = name


class _Pos:
    def __init__(self, i, name, price, qty):
        self.id = name
        self.user_id = USER
        self.instrument = _Inst(name)
        self.segment_type = "MCX_FUT"
        self.quantity = float(qty)
        self.avg_price = price
        self.ltp = price          # flat book; P&L injected via the wallet
        self.opened_at = T0 + timedelta(minutes=i)


def _wire(monkeypatch, wallet_cash: D):
    lev = {n: cx for n, _p, _q, cx in BOOK}
    price = {n: p for n, p, _q, _cx in BOOK}

    async def _settings(user_id, segment, **kw):
        sym = kw.get("symbol") or ""
        name = next(n for n in lev if sym.startswith(n.upper()))
        return {"settings": {
            "selling_overnight": True,
            "margin_calc_mode": "times",
            "overnight_margin_percentage": 100.0,
            "overnight_leverage": float(lev[name]),
            "overnight_fixed_margin_per_lot": 0,
            "min_lot": 1,
        }}

    async def _ltp(token):
        return price[token]

    class _W:
        available_balance = wallet_cash
        used_margin = D(0)
        credit_limit = D(0)

    async def _wallet(user_id, kind):
        return _W()

    from app.services import netting_service, wallet_router
    from app.services import market_data_service as mds
    from app.services import wallet_kinds

    monkeypatch.setattr(netting_service, "get_effective_settings", _settings)
    monkeypatch.setattr(mds, "get_ltp", _ltp)
    monkeypatch.setattr(mds, "get_usd_inr_rate", lambda: 1.0)
    monkeypatch.setattr(mds, "is_usd_quoted_segment", lambda s: False)
    monkeypatch.setattr(wallet_router, "get", _wallet)
    monkeypatch.setattr(wallet_kinds, "wallet_kind_for_segment", lambda s: "MCX")


def _rows():
    return [_Pos(i, n, p, q) for i, (n, p, q, _c) in enumerate(BOOK)]


async def _plan(monkeypatch, wallet_cash: D):
    _wire(monkeypatch, wallet_cash)
    return await ps._fifo_carry_plan(_rows())


# -- the operator's worked example -------------------------------------
async def test_the_oldest_three_are_squared_whole(monkeypatch):
    plan = await _plan(monkeypatch, D("500000"))
    assert plan["Silver"] == 0
    assert plan["Copper"] == 0
    assert plan["Crude"] == 0


async def test_the_newest_carries_untouched_despite_the_smallest_margin(monkeypatch):
    """Gold needs only 2.5 L — the least of the five — and still survives,
    because the rule is first-in-first-squared, not cheapest-first."""
    plan = await _plan(monkeypatch, D("500000"))
    assert plan["Gold"] == D("64.51")


async def test_the_boundary_position_is_squared_only_as_far_as_needed(monkeypatch):
    """~13,180 of 23,980 Zinc squared, ~10,800 carried."""
    plan = await _plan(monkeypatch, D("500000"))
    carried = plan["Zinc"]
    squared = D("23980") - carried
    assert squared == pytest.approx(D("13180"), abs=30)
    assert carried == pytest.approx(D("10800"), abs=30)


# -- P&L moves only the boundary ---------------------------------------
async def test_a_loss_squares_more_of_the_boundary(monkeypatch):
    """-1,00,000 at the close -> about 4,316 more Zinc."""
    flat = await _plan(monkeypatch, D("500000"))
    loss = await _plan(monkeypatch, D("400000"))
    extra = flat["Zinc"] - loss["Zinc"]
    assert extra == pytest.approx(D("4316"), abs=30)


async def test_a_profit_squares_less_of_the_boundary(monkeypatch):
    """+2,00,000 -> about 8,632 fewer Zinc squared."""
    flat = await _plan(monkeypatch, D("500000"))
    profit = await _plan(monkeypatch, D("700000"))
    fewer = profit["Zinc"] - flat["Zinc"]
    assert fewer == pytest.approx(D("8632"), abs=30)


@pytest.mark.parametrize("cash", [D("400000"), D("500000"), D("700000")])
async def test_p_and_l_never_disturbs_the_whole_ones(monkeypatch, cash):
    """Only the boundary moves — the older three stay fully squared and Gold
    stays fully carried."""
    plan = await _plan(monkeypatch, cash)
    assert plan["Silver"] == plan["Copper"] == plan["Crude"] == 0
    assert plan["Gold"] == D("64.51")


# -- the ends of the range ---------------------------------------------
async def test_a_wallet_that_covers_everything_squares_nothing(monkeypatch):
    plan = await _plan(monkeypatch, D("2500000"))
    assert [plan[n] for n, _p, q, _c in BOOK] == [q for _n, _p, q, _c in BOOK]


async def test_an_empty_wallet_squares_the_whole_book(monkeypatch):
    plan = await _plan(monkeypatch, D("0"))
    assert all(v == 0 for v in plan.values())


async def test_the_released_margin_covers_the_shortfall(monkeypatch):
    """4.00 + 4.54 + 5.00 + 3.05 = 16.59 L — the plan must actually close the
    gap, not merely square things in order."""
    plan = await _plan(monkeypatch, D("500000"))
    released = D(0)
    for name, price, qty, cx in BOOK:
        squared = qty - plan[name]
        released += (price * squared) / cx
    need = sum((price * qty) / cx for _n, price, qty, cx in [(n, p, q, c) for n, p, q, c in BOOK])
    assert released == pytest.approx(need - D("500000"), abs=2000)


# -- a contract that will not survive the night ------------------------
async def test_an_expiring_contract_frees_budget_for_the_others(monkeypatch):
    """Gold is the NEWEST, so it was going to carry. Once its 2.5 L no longer
    has to be funded, the boundary position keeps much more: Zinc goes from
    ~10,800 carried to ~21,600."""
    from app.services import instrument_service

    monkeypatch.setattr(
        instrument_service, "effective_expiry",
        lambda inst: date.today() if "GOLD" in inst.symbol else None,
    )
    plan = await _plan(monkeypatch, D("500000"))
    assert "Gold" not in plan                       # settlement path owns it
    assert plan["Zinc"] == pytest.approx(D("21604"), abs=30)


async def test_excluding_one_that_was_being_squared_anyway_changes_nothing(monkeypatch):
    """Crude sat before the boundary, so it was fully squared either way. Its
    margin leaving `need` and its release leaving the total cancel out — the
    boundary must not drift."""
    from app.services import instrument_service

    monkeypatch.setattr(
        instrument_service, "effective_expiry",
        lambda inst: date.today() if "CRUDE" in inst.symbol else None,
    )
    plan = await _plan(monkeypatch, D("500000"))
    assert "Crude" not in plan
    assert plan["Zinc"] == pytest.approx(D("10792"), abs=30)
    assert plan["Gold"] == D("64.51")


async def test_an_expiring_contract_is_never_squared_by_the_planner(monkeypatch):
    """Squaring it at market would rob an option of its intrinsic settlement."""
    from app.services import instrument_service

    monkeypatch.setattr(
        instrument_service, "effective_expiry",
        lambda inst: date.today() if "CRUDE" in inst.symbol else None,
    )
    plan = await _plan(monkeypatch, D("500000"))
    assert plan.get("Crude") is None   # no target => the executor leaves it alone


async def test_a_live_contract_is_unaffected(monkeypatch):
    """Only today-or-earlier counts; a contract expiring later still carries."""
    from app.services import instrument_service

    monkeypatch.setattr(
        instrument_service, "effective_expiry",
        lambda inst: date(2099, 1, 1),
    )
    plan = await _plan(monkeypatch, D("500000"))
    squared = D("23980") - plan["Zinc"]
    assert squared == pytest.approx(D("13180"), abs=30)
