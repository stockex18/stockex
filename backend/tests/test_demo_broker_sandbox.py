"""A demo broker is a working sandbox, and it cannot reach a real wallet.

"Broker ka demo login hota hai — usme 2-3 demo user dikhe, fund add aur
withdraw kar sake, sare features dekh sake, leverage aur settings, aur apne
demo user me trade kara sake."

It used to be read-only on users and funds, with a "switch to real" popup on
New user: a prospective broker could look at every screen and use none of
them. Opening it up is only safe because of what sits underneath, so these
tests pin the underneath as hard as the feature:

  * everything a demo broker creates is demo, however the form is filled in
  * funding a demo user draws the demo broker's own VIRTUAL float
  * a demo user under a REAL owner never touches a real float — found while
    building this: Add Fund on a demo user debited the owning broker's real
    wallet for money that was never real
  * the admin-book, broker cascade and P&L sharing keep skipping demo users

The operator's standing rule: "demo ka kuch bhi admin, super admin ke ledger
ya wallet me nahi aana chahiye."
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

from app.api.v1.admin import users as admin_users
from app.core.exceptions import ConflictError, InsufficientFundsError
from app.services import admin_fund_service as fund
from app.services import demo_service

_REPO = pathlib.Path(__file__).resolve().parents[2]


def _fe(*parts: str) -> str:
    return _REPO.joinpath(*parts).read_text(encoding="utf-8", errors="ignore")


# ── what a demo broker may do ─────────────────────────────────────────
def test_a_demo_broker_can_manage_users_funds_and_trading():
    p = demo_service._demo_broker_permissions()
    for flag in ("users", "deposits", "withdrawals", "trading_view"):
        assert getattr(p, flag) == "EDIT", flag


def test_it_can_still_tune_settings_risk_and_leverage():
    p = demo_service._demo_broker_permissions()
    for flag in ("segment_settings", "risk", "netting", "banks"):
        assert getattr(p, flag) == "EDIT", flag


def test_it_cannot_create_other_brokers():
    """A sub-broker row is real state, not a practice account."""
    assert demo_service._demo_broker_permissions().sub_brokers == "VIEW"


def test_three_practice_clients_come_with_it():
    assert demo_service._DEMO_BROKER_USERS == 3
    assert "await seed_demo_users(broker)" in inspect.getsource(demo_service.create_demo_broker)


# ── the seeded clients ────────────────────────────────────────────────
@pytest.fixture
def seeded(monkeypatch):
    """Run `seed_demo_users` against fakes and report what it asked for."""
    from app.services import user_service

    created: list[dict] = []
    funded: list = []
    calls = {"n": 0, "conflict_first": False}

    class _U(SimpleNamespace):
        async def save(self):
            return None

    async def fake_create_user(**kw):
        calls["n"] += 1
        if calls["conflict_first"] and calls["n"] == 1:
            raise ConflictError("mobile taken", details={"field": "mobile"})
        created.append(kw)
        return _U(id=f"u{len(created)}", account_type=None, **kw)

    async def fake_fund(uid, **kw):
        funded.append(uid)

    monkeypatch.setattr(user_service, "create_user", fake_create_user)
    monkeypatch.setattr(demo_service, "ensure_demo_funding", fake_fund)

    def run(broker=None, **flags):
        calls.update(flags)
        b = broker or SimpleNamespace(
            id="b1", user_code="BRK1", assigned_admin_id=None, broker_ancestry=[]
        )
        out = asyncio.run(demo_service.seed_demo_users(b))
        return out, created, funded

    return run


def test_it_opens_three_clients(seeded):
    out, created, _ = seeded()
    assert len(out) == 3 and len(created) == 3


def test_every_seeded_client_is_demo(seeded):
    _, created, _ = seeded()
    assert all(kw["is_demo"] is True for kw in created)


def test_they_hang_off_the_demo_broker_and_nothing_real(seeded):
    """Platform pool, no admin above them — so there is no real wallet in
    reach of anything they do."""
    _, created, _ = seeded()
    for kw in created:
        assert kw["assigned_broker_id"] == "b1"
        assert kw["assigned_admin_id"] is None
        assert kw["broker_ancestry"] == ["b1"]
        assert kw["created_by"] == "b1"


def test_each_one_is_funded_with_demo_money(seeded):
    _, _, funded = seeded()
    assert len(funded) == 3


def test_their_credentials_are_random_and_distinct(seeded):
    _, created, _ = seeded()
    assert len({kw["mobile"] for kw in created}) == 3
    assert len({kw["email"] for kw in created}) == 3
    assert len({kw["password"] for kw in created}) == 3
    assert all(kw["email"].endswith("@demo.local") for kw in created)


def test_a_mobile_collision_is_retried_not_fatal(seeded):
    """A random mobile can, rarely, collide. That must not cost the broker a
    client or fail the signup."""
    out, created, _ = seeded(conflict_first=True)
    assert len(out) == 3


def test_a_demo_broker_under_a_real_admin_inherits_nothing_real_it_did_not_have(seeded):
    """The chain is copied from the broker as it is, the way a hand-made client
    would be — still demo, still flagged."""
    b = SimpleNamespace(id="b9", user_code="BRK9", assigned_admin_id="adm1", broker_ancestry=["top"])
    _, created, _ = seeded(broker=b)
    assert created[0]["broker_ancestry"] == ["top", "b9"]
    assert created[0]["assigned_admin_id"] == "adm1"
    assert all(kw["is_demo"] for kw in created)


# ── everything a demo broker creates is demo ─────────────────────────
def test_the_create_endpoint_forces_demo_for_a_demo_broker():
    src = inspect.getsource(admin_users.create_user)
    assert 'make_demo = bool(payload.is_demo) or bool(getattr(admin, "is_demo", False))' in src


def test_nothing_downstream_still_reads_the_checkbox():
    """Every later use has to read the forced value; one stray read of the raw
    form field would put the rule back in the user's hands."""
    src = inspect.getsource(admin_users.create_user)
    assert src.count("payload.is_demo") == 1


def test_a_demo_broker_cannot_flip_a_user_to_real():
    src = inspect.getsource(admin_users.update_user)
    assert 'getattr(admin, "is_demo", False) and payload.get("is_demo") is False' in src
    assert "status_code=403" in src


# ── the float guard ───────────────────────────────────────────────────
@pytest.fixture
def floats(monkeypatch):
    """Drive debit/credit_admin_float_for_user with fakes, report every wallet
    movement they make."""
    moves: list[tuple] = []

    class _Owner(SimpleNamespace):
        pass

    owners: dict[str, _Owner] = {}

    async def fake_owning(user_or_id):
        return user_or_id.owner_id, "SA", user_or_id

    async def fake_user_get(_id):
        return owners.get(str(_id))

    async def fake_adjust(uid, amt, **kw):
        moves.append((str(uid), float(amt), str(kw.get("transaction_type"))))

    balance = {"v": 1_000_000}

    async def fake_wallet(uid):
        return SimpleNamespace(available_balance=balance["v"])

    monkeypatch.setattr(fund, "_owning_admin_id", fake_owning)
    monkeypatch.setattr(fund.User, "get", staticmethod(fake_user_get), raising=False)
    monkeypatch.setattr(fund.wallet_service, "adjust", fake_adjust)
    monkeypatch.setattr(fund.wallet_service, "get_or_create", fake_wallet)

    def setup(*, user_demo: bool, owner_demo: bool, float_balance: int = 1_000_000):
        balance["v"] = float_balance
        # A real ObjectId, because the code under test builds one from it.
        oid = str(PydanticObjectId())
        owners[oid] = _Owner(is_demo=owner_demo)
        return SimpleNamespace(owner_id=oid, is_demo=user_demo, user_code="CL1")

    return setup, moves


def test_a_demo_user_under_a_real_owner_never_debits_the_real_float(floats):
    setup, moves = floats
    u = setup(user_demo=True, owner_demo=False)
    asyncio.run(fund.debit_admin_float_for_user(u, 5000, reference_type="ADJUSTMENT"))
    assert moves == []


def test_nor_does_the_withdrawal_pay_a_real_float_back(floats):
    """Nothing was taken, so nothing is returned — otherwise a real float
    would GROW by every demo withdrawal."""
    setup, moves = floats
    u = setup(user_demo=True, owner_demo=False)
    asyncio.run(fund.credit_admin_float_for_user(u, 5000, reference_type="ADJUSTMENT"))
    assert moves == []


def test_a_demo_user_under_a_demo_broker_draws_the_virtual_float(floats):
    """The point of the demo: fund a client and watch your float fall."""
    setup, moves = floats
    u = setup(user_demo=True, owner_demo=True)
    asyncio.run(fund.debit_admin_float_for_user(u, 5000, reference_type="ADJUSTMENT"))
    assert len(moves) == 1
    assert moves[0][0] == u.owner_id and moves[0][1] == -5000.0


def test_and_defunding_returns_it(floats):
    setup, moves = floats
    u = setup(user_demo=True, owner_demo=True)
    asyncio.run(fund.credit_admin_float_for_user(u, 3000, reference_type="ADJUSTMENT"))
    assert len(moves) == 1 and moves[0][1] == 3000.0


def test_the_virtual_float_runs_out_like_a_real_one(floats):
    """A demo that lets you fund without limit teaches the wrong thing."""
    setup, moves = floats
    u = setup(user_demo=True, owner_demo=True, float_balance=1000)
    with pytest.raises(InsufficientFundsError):
        asyncio.run(fund.debit_admin_float_for_user(u, 5000, reference_type="ADJUSTMENT"))
    assert moves == []


def test_a_real_user_under_a_real_owner_is_untouched_by_the_guard(floats):
    """The guard must not have loosened the normal path."""
    setup, moves = floats
    u = setup(user_demo=False, owner_demo=False)
    asyncio.run(fund.debit_admin_float_for_user(u, 5000, reference_type="ADJUSTMENT"))
    assert len(moves) == 1 and moves[0][1] == -5000.0


# ── what keeps demo trades out of the books ──────────────────────────
def test_the_admin_book_still_skips_demo_users():
    from app.services import admin_book_service

    src = inspect.getsource(admin_book_service)
    assert 'if getattr(user, "is_demo", False):' in src


def test_pnl_sharing_still_filters_demo_clients():
    from app.services import pnl_sharing_service

    assert '"is_demo": {"$ne": True}' in inspect.getsource(pnl_sharing_service)


# ── the admin app ─────────────────────────────────────────────────────
def test_new_user_no_longer_opens_the_switch_to_real_popup():
    s = _fe("frontend-admin", "app", "(admin)", "users", "page.tsx")
    assert "demoBlock" not in s
    assert "Switch to a real broker to add users" not in s
    assert 'href="/users/new"' in s


def test_a_demo_broker_lands_on_the_demo_tab():
    """Its clients are all demo, so the Live tab would be permanently empty."""
    s = _fe("frontend-admin", "app", "(admin)", "users", "page.tsx")
    assert "if (isDemoBroker) setMode(\"demo\")" in s


def test_the_new_user_form_says_what_will_happen():
    s = _fe("frontend-admin", "app", "(admin)", "users", "new", "page.tsx")
    assert "is_demo: admin?.is_demo ? true : rest.is_demo" in s
    assert "every user you create is a demo account" in s


def test_the_banner_no_longer_claims_creation_is_locked():
    s = _fe("frontend-admin", "components", "common", "DemoBrokerBanner.tsx")
    assert "user creation is locked" not in s
