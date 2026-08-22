"""Security money — the arithmetic the operator specified, as a worked example.

    admin lodges 5,00,000        security 5,00,000   payable        0
    a user of theirs LOSES 300   security 4,99,700   payable      300
    a user of theirs WINS 1L     security 5,99,700   payable      300

Direction is the whole feature and it is easy to invert, so most of these
tests are that table rather than the plumbing around it.
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
    def __init__(self):
        self.admin_id = ADMIN
        self.security_balance = Decimal128("0")
        self.payable_balance = Decimal128("0")
        self.total_deposited = Decimal128("0")
        self.total_games_in = Decimal128("0")
        self.total_games_out = Decimal128("0")

    async def save(self):
        return None


def _wire(monkeypatch):
    row = _Row()
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


async def _games(row_admin, house_amt: D):
    """Apply one games settle the way the hook does."""
    await svc._apply(
        row_admin,
        entry_type=SecurityEntryType.GAMES_PNL,
        security_delta=-house_amt,
        payable_delta=house_amt if house_amt > D("0") else D("0"),
    )


# -- the operator's worked example, step by step ----------------------
async def test_deposit_does_not_create_payable(monkeypatch):
    """Collateral being HELD is not something earned."""
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.DEPOSIT, security_delta=D("500000"))
    assert _sec(row) == D("500000")
    assert _pay(row) == D("0")


async def test_loss_lowers_security_and_raises_payable(monkeypatch):
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.DEPOSIT, security_delta=D("500000"))
    await _games(ADMIN, D("300"))  # house collected 300 -> player lost
    assert _sec(row) == D("499700")
    assert _pay(row) == D("300")


async def test_win_raises_security_and_leaves_payable(monkeypatch):
    """A win is absorbed by the collateral; it does not net off payable."""
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.DEPOSIT, security_delta=D("500000"))
    await _games(ADMIN, D("300"))
    await _games(ADMIN, D("-100000"))  # house paid 1L -> player won
    assert _sec(row) == D("599700")
    assert _pay(row) == D("300")


async def test_full_example_end_to_end(monkeypatch):
    """The whole table in one run — the numbers the operator gave."""
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.DEPOSIT, security_delta=D("500000"))
    assert (_sec(row), _pay(row)) == (D("500000"), D("0"))
    await _games(ADMIN, D("300"))
    assert (_sec(row), _pay(row)) == (D("499700"), D("300"))
    await _games(ADMIN, D("-100000"))
    assert (_sec(row), _pay(row)) == (D("599700"), D("300"))


# -- how payable comes back down --------------------------------------
async def test_sa_topup_raises_security_and_lowers_payable(monkeypatch):
    """The only thing that reduces payable: the SA actually funding it."""
    row, _ = _wire(monkeypatch)
    await _games(ADMIN, D("1000"))            # payable 1000, security -1000
    await svc._apply(
        ADMIN, entry_type=SecurityEntryType.SA_TOPUP,
        security_delta=D("400"), payable_delta=D("-400"),
    )
    assert _pay(row) == D("600")
    assert _sec(row) == D("-600")


async def test_return_to_admin_touches_only_security(monkeypatch):
    row, _ = _wire(monkeypatch)
    await svc._apply(ADMIN, entry_type=SecurityEntryType.DEPOSIT, security_delta=D("500"))
    await svc._apply(ADMIN, entry_type=SecurityEntryType.WITHDRAW, security_delta=D("-200"))
    assert (_sec(row), _pay(row)) == (D("300"), D("0"))


# -- rollups ----------------------------------------------------------
async def test_rollups_follow_the_player_not_the_sign(monkeypatch):
    """`security_delta` is inverted here, so "in" must still mean player-lost."""
    row, _ = _wire(monkeypatch)
    await _games(ADMIN, D("300"))       # player lost
    await _games(ADMIN, D("-100000"))   # player won
    assert D(str(row.total_games_in)) == D("300")
    assert D(str(row.total_games_out)) == D("100000")


# -- ledger + guards --------------------------------------------------
async def test_every_move_writes_a_ledger_row(monkeypatch):
    row, entries = _wire(monkeypatch)
    await _games(ADMIN, D("300"))
    assert len(entries) == 1
    assert D(str(entries[0]["security_after"])) == D("-300")
    assert D(str(entries[0]["payable_after"])) == D("300")


def test_balances_move_in_exactly_one_place():
    src = inspect.getsource(svc)
    body = src[src.index("async def record_deposit"):]
    assert "security_balance =" not in body
    assert "payable_balance =" not in body


def test_deposit_and_withdraw_never_pass_payable():
    """The correction: lodging or returning collateral must not move payable."""
    for fn in (svc.record_deposit, svc.record_withdraw):
        assert "payable_delta" not in inspect.getsource(fn)


@pytest.mark.parametrize("bad", [0, -1, "-5"])
async def test_non_positive_amounts_rejected(bad):
    with pytest.raises(Exception):
        svc._positive(bad)


async def test_games_hook_is_a_noop_for_demo_players(monkeypatch):
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
    from app.services.games import wallet_service as gws

    assert "apply_games_result" in inspect.getsource(gws.house_settle)


def test_hook_inverts_the_house_sign():
    """If this ever became `security_delta=amt` the whole feature runs backwards."""
    src = inspect.getsource(svc.apply_games_result)
    assert "security_delta=-amt" in src


def test_topup_debits_the_wallet_before_writing():
    src = inspect.getsource(svc.topup_from_main)
    assert src.index("wallet_service.adjust") < src.index("_apply(")
