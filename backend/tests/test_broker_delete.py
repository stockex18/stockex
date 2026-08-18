"""Broker delete guards.

Destructive and reachable by any owning ADMIN (not just the super admin), so
the refusal rules are the safety net: a broker is the parent of real accounts
and real money, and cascading would orphan them.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId
from bson import Decimal128

from app.core.exceptions import ConflictError
from app.models.user import UserStatus
from app.services import broker_management_service as svc


def _broker(**kw):
    b = SimpleNamespace(
        id=PydanticObjectId(),
        status=UserStatus.ACTIVE,
        is_demo=False,
        email="b@x.com",
        mobile="9998887770",
        token_version=0,
        deleted_email_original=None,
        deleted_mobile_original=None,
    )
    for k, v in kw.items():
        setattr(b, k, v)
    b.save = _noop
    b.delete = _noop
    return b


async def _noop(*a, **k):
    return None


def _wire(monkeypatch, broker, *, clients=0, sub_brokers=0, balance="0", used="0"):
    """Stub the scope check, the two counts and the wallet lookup."""
    saved = {}

    async def _scope(actor, bid):
        return broker

    class _Cursor:
        def __init__(self, n):
            self._n = n

        async def count(self):
            return self._n

        async def delete(self):
            saved["wallet_deleted"] = True

    def _find(q):
        if q.get("role") == "CLIENT":
            return _Cursor(clients)
        if q.get("role") == "BROKER":
            return _Cursor(sub_brokers)
        return _Cursor(0)

    async def _find_one(*a, **k):
        return SimpleNamespace(
            available_balance=Decimal128(balance), used_margin=Decimal128(used)
        )

    async def _log(**k):
        saved["logged"] = k
        return None

    monkeypatch.setattr(svc, "assert_broker_in_scope", _scope)
    monkeypatch.setattr(svc.User, "find", staticmethod(_find))
    monkeypatch.setattr(svc, "log_event", _log)

    import app.models.wallet as wmod

    monkeypatch.setattr(wmod.Wallet, "find_one", staticmethod(_find_one))
    monkeypatch.setattr(wmod.Wallet, "find", staticmethod(lambda q: _Cursor(0)))
    return saved


ACTOR = SimpleNamespace(id=PydanticObjectId())


async def test_refuses_while_clients_remain(monkeypatch):
    b = _broker()
    _wire(monkeypatch, b, clients=3)
    with pytest.raises(ConflictError) as e:
        await svc.delete_broker(ACTOR, b.id)
    assert "3 active client" in str(e.value)
    assert b.status == UserStatus.ACTIVE  # untouched


async def test_refuses_while_sub_brokers_remain(monkeypatch):
    b = _broker()
    _wire(monkeypatch, b, sub_brokers=2)
    with pytest.raises(ConflictError) as e:
        await svc.delete_broker(ACTOR, b.id)
    assert "2 sub-broker" in str(e.value)


async def test_refuses_while_wallet_holds_money(monkeypatch):
    """Funds would simply stop being reachable by anyone."""
    b = _broker()
    _wire(monkeypatch, b, balance="4500.50")
    with pytest.raises(ConflictError) as e:
        await svc.delete_broker(ACTOR, b.id)
    assert "4500.50" in str(e.value)


async def test_refuses_while_margin_in_use(monkeypatch):
    b = _broker()
    _wire(monkeypatch, b, used="900")
    with pytest.raises(ConflictError):
        await svc.delete_broker(ACTOR, b.id)


async def test_reports_every_blocker_at_once(monkeypatch):
    """One round trip should tell the admin everything to clear."""
    b = _broker()
    _wire(monkeypatch, b, clients=1, sub_brokers=1, balance="10")
    with pytest.raises(ConflictError) as e:
        await svc.delete_broker(ACTOR, b.id)
    msg = str(e.value)
    assert "client" in msg and "sub-broker" in msg and "wallet" in msg


async def test_clean_broker_is_soft_closed(monkeypatch):
    b = _broker()
    _wire(monkeypatch, b)
    out = await svc.delete_broker(ACTOR, b.id)
    assert out["status"] == UserStatus.CLOSED.value
    assert b.status == UserStatus.CLOSED


async def test_contact_is_tombstoned_so_it_can_re_register(monkeypatch):
    """The unique index does not know about CLOSED — without freeing these,
    the same person could never sign up again."""
    b = _broker(email="raj@x.com", mobile="9876543210")
    _wire(monkeypatch, b)
    await svc.delete_broker(ACTOR, b.id)
    assert b.deleted_email_original == "raj@x.com"
    assert b.email == f"raj+deleted-{b.id}@x.com"
    assert b.deleted_mobile_original == "9876543210"
    assert b.mobile.startswith("DEL")


async def test_tokens_are_invalidated(monkeypatch):
    """Otherwise a deleted broker keeps working for up to 15 minutes."""
    b = _broker(token_version=7)
    _wire(monkeypatch, b)
    await svc.delete_broker(ACTOR, b.id)
    assert b.token_version == 8


async def test_already_deleted_is_rejected(monkeypatch):
    b = _broker(status=UserStatus.CLOSED)
    _wire(monkeypatch, b)
    with pytest.raises(ConflictError):
        await svc.delete_broker(ACTOR, b.id)


async def test_demo_broker_ignores_blockers_and_hard_deletes(monkeypatch):
    b = _broker(is_demo=True)
    saved = _wire(monkeypatch, b, clients=5, balance="999")
    out = await svc.delete_broker(ACTOR, b.id)
    assert out["status"] == "deleted"
    assert saved.get("logged", {}).get("metadata", {}).get("mode") == "hard"
