"""Daily platform charge (Settings -> Platform -> "Platform charge per user /
day"). The super-admin's 🪙25 switched on in October had charged nobody: the
sweep only looked for users assigned to the super-admin, and every client sits
under an admin. It also read MAIN only, where most users hold 🪙0."""

import asyncio
import inspect
import types
from decimal import Decimal

from bson import ObjectId

from app.services import platform_maintenance_service as pm

SA, ADM, OTHER = ObjectId(), ObjectId(), ObjectId()


def _u(assigned):
    return types.SimpleNamespace(id=ObjectId(), assigned_admin_id=assigned)


def test_super_admin_charge_covers_every_pool_and_an_admins_own_replaces_it():
    sa = types.SimpleNamespace(id=SA)
    adm = types.SimpleNamespace(id=ADM)
    chargers = {SA: sa, ADM: adm}
    assert pm._charger_for(_u(OTHER), chargers, sa) is sa  # admin without own charge
    assert pm._charger_for(_u(None), chargers, sa) is sa  # platform pool
    assert pm._charger_for(_u(ADM), chargers, sa) is adm  # admin's own, not both
    assert pm._charger_for(_u(OTHER), {ADM: adm}, None) is None  # SA off: only ADM's pool


def test_fee_comes_from_main_then_trading_wallets_never_below_zero(monkeypatch):
    main = {"bal": Decimal("10")}
    seg = {"NSE_BSE": Decimal("8"), "MCX": Decimal("100"), "CRYPTO": Decimal("0"), "FOREX": Decimal("0")}
    debits = []

    async def main_get(_uid):
        return types.SimpleNamespace(available_balance=main["bal"])

    async def main_adj(_uid, amt, **_kw):
        main["bal"] += amt
        debits.append(("MAIN", amt))

    async def seg_get(_uid, kind):
        return types.SimpleNamespace(available_balance=seg[kind])

    async def seg_adj(_uid, kind, amt, **_kw):
        seg[kind] += amt
        debits.append((kind, amt))

    monkeypatch.setattr(pm.wallet_service, "get_or_create", main_get)
    monkeypatch.setattr(pm.wallet_service, "adjust", main_adj)
    monkeypatch.setattr(pm.segment_wallet_service, "get_or_create", seg_get)
    monkeypatch.setattr(pm.segment_wallet_service, "adjust", seg_adj)

    def run(fee):
        return asyncio.run(pm._debit_fee(ObjectId(), Decimal(fee), narration="x", actor_id=SA))

    assert run("25") == Decimal("25")
    assert debits == [("MAIN", Decimal("-10")), ("NSE_BSE", Decimal("-8")), ("MCX", Decimal("-7"))]
    assert main["bal"] == 0 and seg["NSE_BSE"] == 0 and seg["MCX"] == Decimal("93")

    # Not enough anywhere: take what there is, nothing goes negative.
    seg["MCX"] = Decimal("3")
    assert run("25") == Decimal("3")
    assert min(main["bal"], *seg.values()) >= 0


def test_demo_accounts_are_never_charged():
    assert '"is_demo": {"$ne": True}' in inspect.getsource(pm.run_platform_charge_sweep)
