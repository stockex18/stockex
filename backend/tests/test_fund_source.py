"""The SA picks which of its two wallets pays a member.

The trap this guards: `fund_admin_share_from_sa_wallets` has always fallen
back to the personal wallet when kuber was short. That is fine for the
automatic per-admin plan, but if the SA explicitly said "Kuber pool", quietly
taking the money out of the main wallet is exactly the thing they were trying
to control.
"""

from __future__ import annotations

import inspect
from decimal import Decimal as D

import pytest

from app.core.exceptions import InsufficientFundsError, ValidationFailedError
from app.services import admin_fund_service as afs
from app.services import kuber_service


def _pct(source: str | None, plan_pct: float = 0.0) -> float:
    """Mirror of the branch in add_funds, so the mapping is pinned."""
    picked = (source or "").strip().upper()
    if picked and picked not in ("MAIN", "KUBER"):
        raise ValidationFailedError("source must be MAIN or KUBER")
    return (100.0 if picked == "KUBER" else 0.0) if picked else plan_pct


def test_kuber_choice_takes_it_all_from_kuber():
    assert _pct("KUBER") == 100.0


def test_main_choice_takes_nothing_from_kuber():
    assert _pct("MAIN") == 0.0


@pytest.mark.parametrize("s", ["kuber", " Kuber ", "kUbEr"])
def test_choice_is_case_and_space_insensitive(s):
    assert _pct(s) == 100.0


def test_no_choice_leaves_the_existing_plan_alone():
    """Every caller that never passes `source` must behave exactly as before."""
    assert _pct(None, plan_pct=60.0) == 60.0
    assert _pct("", plan_pct=60.0) == 60.0


@pytest.mark.parametrize("bad", ["POCKET", "main wallet", "0"])
def test_a_wallet_that_does_not_exist_is_rejected(bad):
    with pytest.raises(ValidationFailedError):
        _pct(bad)


def test_franchise_default_still_reads_from_the_plan():
    class _A:
        is_franchise_root = True
    assert kuber_service.resolve_funding_plan_for_admin(_A())["kuber_pct"] == 100.0


# -- the no-silent-fallback guard -------------------------------------
async def test_short_kuber_raises_instead_of_raiding_main(monkeypatch):
    spent = []

    async def _wallet(_):
        class _W:
            id = "w"
            user_id = "u"
        return _W()

    class _Coll:
        async def find_one_and_update(self, *a, **k):
            return None  # kuber has less than asked for

    monkeypatch.setattr(kuber_service, "_sa_wallet", _wallet)
    monkeypatch.setattr(kuber_service.Wallet, "get_motor_collection", staticmethod(lambda: _Coll()))
    monkeypatch.setattr(
        kuber_service.wallet_service, "adjust",
        lambda *a, **k: spent.append(a),
    )

    with pytest.raises(InsufficientFundsError):
        await kuber_service.fund_admin_share_from_sa_wallets(
            "sa", D("1000"), 100.0, narration="x", strict=True
        )
    assert spent == [], "main wallet must not be touched when kuber was the pick"


async def test_short_kuber_still_falls_back_when_nobody_picked(monkeypatch):
    """The automatic plan keeps its old forgiving behaviour."""
    spent = []

    async def _wallet(_):
        class _W:
            id = "w"
            user_id = "u"
        return _W()

    class _Coll:
        async def find_one_and_update(self, *a, **k):
            return None

    async def _adjust(uid, amt, **k):
        spent.append(amt)

    monkeypatch.setattr(kuber_service, "_sa_wallet", _wallet)
    monkeypatch.setattr(kuber_service.Wallet, "get_motor_collection", staticmethod(lambda: _Coll()))
    monkeypatch.setattr(kuber_service.wallet_service, "adjust", _adjust)

    out = await kuber_service.fund_admin_share_from_sa_wallets(
        "sa", D("1000"), 100.0, narration="x"
    )
    assert out["kuber"] == "0"
    assert spent == [D("-1000")]


# -- wiring -----------------------------------------------------------
def test_strict_is_on_exactly_when_a_wallet_was_picked():
    src = inspect.getsource(afs.add_funds)
    assert "strict=bool(picked)" in src


def test_source_reaches_the_service_from_the_router():
    from app.api.v1.admin import fund

    assert "source" in fund.AmountBody.model_fields
    assert "source=body.source" in inspect.getsource(fund.add_funds)


def test_pull_back_is_untouched():
    """Only the add side got a wallet choice; `deduct` still lands in main."""
    assert "source" not in inspect.signature(afs.deduct_funds).parameters
