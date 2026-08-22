"""Security money — collateral direction and payable ownership.

The direction is the whole feature, and it is easy to invert: security carries
the HOUSE's sign (player loses -> collateral up), while `payable` tracks who
OWNS the money and games must never move it.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest
from beanie import PydanticObjectId
from bson import Decimal128

from app.models.admin_security import SecurityEntryType
from app.services import admin_security_service as svc

ADMIN = PydanticObjectId()


class _Row:
    """Stands in for the AdminSecurity document."""

    def __init__(self):
        self.admin_id = ADMIN
        self.security_balance = Decimal128("0")
        self.payable_balance = Decimal128("0")
        self.total_deposited = Decimal128("0")
        self.total_games_in = Decimal128("0")
        self.total_games_out = Decimal128("0")

    async def save(self):
        return None


def _wire(monkeypatch, row=None):
    row = row or _Row()
    entries = []

    async def _get_or_create(_):
        return row

    class _Entry:
        def __init__(self, **kw):
            self.kw = kw

        async def insert(self):
            entries.append(self.kw)

    monkeypatch.setattr(svc, "get_or_create", _get_or_create)
    monkeypatch.setattr(svc, "AdminSecurityEntry", _Entry)
    return row, entries


def _sec(row):
    return D(str(row.security_balance))


def _pay(row):
    return D(str(row.payable_balance))


# -- games direction --------------------------------------------------
async def test_player_loses_so_collateral_goes_up(monkeypatch):
    """House collected (+) -> security up. Security carries the house's sign."""
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("100000"))
    assert _sec(row) == D("100000")


async def test_player_wins_so_collateral_goes_down(monkeypatch):
    """The operator's case: a 1L win eats 1L of that admin's collateral."""
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("500000"))
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("-100000"))
    assert _sec(row) == D("400000")


async def test_games_never_touch_payable(monkeypatch):
    """Games move the collateral, not who owns it."""
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("100000"))
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("-250000"))
    assert _pay(row) == D("0")


async def test_games_rollups_split_by_direction(monkeypatch):
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("300"))
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("-200"))
    assert D(str(row.total_games_in)) == D("300")
    assert D(str(row.total_games_out)) == D("200")  # stored as a magnitude


# -- ownership --------------------------------------------------------
async def test_admin_deposit_raises_both(monkeypatch):
    """Their money: collateral up, and we now owe it back."""
    row, _ = _wire(monkeypatch)
    await svc._apply(
        ADMIN, entry_type=SecurityEntryType.DEPOSIT,
        security_delta=D("1000000"), payable_delta=D("1000000"),
    )
    assert _sec(row) == D("1000000")
    assert _pay(row) == D("1000000")


async def test_sa_topup_raises_security_but_LOWERS_payable(monkeypatch):
    """The rule the operator gave: SA's own money going in settles the debt
    rather than adding to it."""
    row, _ = _wire(monkeypatch)
    await svc._apply(
        ADMIN, entry_type=SecurityEntryType.DEPOSIT,
        security_delta=D("1000000"), payable_delta=D("1000000"),
    )
    await svc._apply(
        ADMIN, entry_type=SecurityEntryType.SA_TOPUP,
        security_delta=D("400000"), payable_delta=D("-400000"),
    )
    assert _sec(row) == D("1400000")
    assert _pay(row) == D("600000")


async def test_return_to_admin_lowers_both(monkeypatch):
    row, _ = _wire(monkeypatch)
    await svc._apply(
        ADMIN, entry_type=SecurityEntryType.DEPOSIT,
        security_delta=D("500"), payable_delta=D("500"),
    )
    await svc._apply(
        ADMIN, entry_type=SecurityEntryType.WITHDRAW,
        security_delta=D("-200"), payable_delta=D("-200"),
    )
    assert (_sec(row), _pay(row)) == (D("300"), D("300"))


# -- ledger -----------------------------------------------------------
async def test_every_move_writes_a_ledger_row(monkeypatch):
    """A balance must always be replayable from its rows."""
    row, entries = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.GAMES_PNL, security_delta=D("100"))
    assert len(entries) == 1
    e = entries[0]
    assert D(str(e["amount"])) == D("100")
    assert D(str(e["security_after"])) == D("100")


def test_balances_move_in_exactly_one_place():
    """Two writers means nobody can reconcile it later."""
    src = inspect.getsource(svc)
    body = src[src.index("async def record_deposit"):]
    assert "security_balance =" not in body
    assert "payable_balance =" not in body


# -- guards -----------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1, "-5"])
async def test_deposit_rejects_non_positive(bad):
    with pytest.raises(Exception):
        svc._positive(bad)


async def test_games_hook_is_a_noop_for_demo_players(monkeypatch):
    """Virtual play must never consume a real admin's collateral."""
    called = []
    monkeypatch.setattr(svc, "_apply", lambda *a, **k: called.append(1))

    class _U:
        id = PydanticObjectId()
        is_demo = True
        assigned_admin_id = ADMIN

    async def _get(_):
        return _U()

    monkeypatch.setattr(svc.User, "get", staticmethod(_get))
    await svc.apply_games_result(PydanticObjectId(), D("100"), game_key="x")
    assert called == []


async def test_games_hook_is_a_noop_without_an_owning_admin(monkeypatch):
    called = []
    monkeypatch.setattr(svc, "_apply", lambda *a, **k: called.append(1))

    class _U:
        id = PydanticObjectId()
        is_demo = False
        assigned_admin_id = None

    async def _get(_):
        return _U()

    monkeypatch.setattr(svc.User, "get", staticmethod(_get))
    await svc.apply_games_result(PydanticObjectId(), D("100"), game_key="x")
    assert called == []


async def test_games_hook_never_raises(monkeypatch):
    """It runs on the payout path — a winner must be paid regardless."""
    async def _boom(_):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc.User, "get", staticmethod(_boom))
    await svc.apply_games_result(PydanticObjectId(), D("100"), game_key="x")


def test_hook_runs_from_house_settle():
    """A hook nobody calls tracks nothing."""
    from app.services.games import wallet_service as gws

    src = inspect.getsource(gws.house_settle)
    assert "apply_games_result" in src


def test_topup_debits_the_wallet_before_writing():
    """Insufficient funds must abort before either side is written, or the
    collateral and the wallet drift apart."""
    src = inspect.getsource(svc.topup_from_main)
    assert src.index("wallet_service.adjust") < src.index("_apply(")
