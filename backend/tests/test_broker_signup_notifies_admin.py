"""A broker who signs up is announced to the admin they chose.

Before this, `broker_register` only wrote a log line: the account sat PENDING
— unable to sign in — until somebody happened to open the Brokers page. Now
the chosen admin (the broker's owner, and the one who can approve it) gets a
bell row, a live toast, and an open Brokers page refreshes. None of that may
fail the registration, which is already saved by then.
"""

from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace

import pytest

from app.api.v1.admin import auth as admin_auth
from app.models.notification import AdminNotificationEventType
from app.services import admin_events, broker_management_service, broker_search_service
from app.services import notification_service

ADMIN = SimpleNamespace(id="adm1", full_name="Ankit", user_code="ADM1")


class _Broker(SimpleNamespace):
    async def save(self):
        self.saved = True


@pytest.fixture
def signup(monkeypatch):
    calls: dict[str, list] = {"notify": [], "event": []}
    broker = _Broker(id="brk1", full_name="Priya", user_code="BRK0001", status=None)

    async def resolve(_id):
        return ADMIN

    async def create_broker(**_kw):
        return broker

    async def notify(*args, **kwargs):
        calls["notify"].append((args, kwargs))
        return 1

    async def publish(event_type, payload=None):
        calls["event"].append((event_type, payload))

    monkeypatch.setattr(broker_search_service, "resolve_signup_admin", resolve)
    monkeypatch.setattr(broker_management_service, "create_broker", create_broker)
    monkeypatch.setattr(notification_service, "create_for_admins", notify)
    monkeypatch.setattr(admin_events, "publish_admin_event", publish)

    payload = admin_auth.BrokerRegisterRequest(
        full_name="Priya", email="p@x.co", mobile="9876543210", password="Abcdefg1",
        admin_id="adm1", gender="FEMALE", city="Delhi", pincode="110099",
    )

    def run():
        return asyncio.run(admin_auth.broker_register(payload, None))

    return run, calls, broker, monkeypatch


def test_the_chosen_admin_gets_a_bell_row(signup):
    run, calls, broker, _ = signup
    run()
    assert broker.saved
    (args, kwargs), = calls["notify"]
    # The source is the new broker; recipients resolve to its owner, the
    # chosen admin (create_broker stamps assigned_admin_id = that admin).
    assert args[0] == "brk1"
    assert args[1] is AdminNotificationEventType.BROKER_REGISTERED
    assert "awaiting approval" in args[2]
    assert "Priya (BRK0001)" in args[3] and "Delhi 110099" in args[3]
    assert kwargs["link"] == "/management/brokers"


def test_a_live_event_reaches_only_the_chosen_admin(signup):
    run, calls, _, _ = signup
    run()
    (event_type, payload), = calls["event"]
    assert event_type == "broker_update"
    assert payload["event"] == "registered"
    assert payload["recipient_admin_ids"] == ["adm1"]


def test_a_failed_notification_does_not_fail_the_signup(signup):
    run, _, broker, monkeypatch = signup

    async def boom(*_a, **_k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(notification_service, "create_for_admins", boom)
    monkeypatch.setattr(admin_events, "publish_admin_event", boom)
    out = run()
    assert broker.saved
    assert out.data["user_code"] == "BRK0001"


def test_the_bell_and_the_bridge_know_the_new_event():
    root = pathlib.Path(__file__).resolve().parents[2]
    bell = (root / "frontend-admin/components/layout/NotificationBell.tsx").read_text(encoding="utf-8")
    bridge = (root / "frontend-admin/components/common/AdminWsBridge.tsx").read_text(encoding="utf-8")
    assert 'case "BROKER_REGISTERED":' in bell
    assert 'case "broker_update":' in bridge
