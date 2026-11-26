"""With the super admin's weekly-settlement switch OFF, an admin's "Run now"
is refused too (operator, 26 Nov: off for the whole platform, every admin).
The super admin can still run it by hand."""

import asyncio
import types

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api.v1.admin import settings as settings_api
from app.core import dependencies
from app.models.user import UserRole
from app.services import audit_service, weekly_settlement_service as wss


def _wire(monkeypatch, enabled):
    ran = []

    async def flag():
        return enabled

    async def run(**kw):
        ran.append(kw)
        return {"week_key": "2026-W48", "settled": 0}

    async def scoped(_admin):
        return []

    async def log(**_kw):
        return None

    monkeypatch.setattr(wss, "is_settlement_enabled", flag)
    monkeypatch.setattr(wss, "run_weekly_settlement", run)
    monkeypatch.setattr(dependencies, "scoped_user_ids", scoped)
    monkeypatch.setattr(settings_api, "log_event", log)
    monkeypatch.setattr(audit_service, "log_event", log)
    return ran


def _actor(role):
    return types.SimpleNamespace(id=ObjectId(), role=role)


def test_an_admin_cannot_run_it_while_the_platform_switch_is_off(monkeypatch):
    ran = _wire(monkeypatch, enabled=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(settings_api.trigger_weekly_settlement(_actor(UserRole.ADMIN), force=True))
    assert e.value.status_code == 400 and "turned off" in e.value.detail
    assert ran == []


def test_the_super_admin_still_can(monkeypatch):
    ran = _wire(monkeypatch, enabled=False)
    asyncio.run(settings_api.trigger_weekly_settlement(_actor(UserRole.SUPER_ADMIN), force=True))
    assert len(ran) == 1


def test_an_admin_runs_it_when_the_switch_is_on(monkeypatch):
    ran = _wire(monkeypatch, enabled=True)
    asyncio.run(settings_api.trigger_weekly_settlement(_actor(UserRole.ADMIN), force=True))
    assert len(ran) == 1
