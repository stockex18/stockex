"""Leads from the /start landing page.

What has to hold:

  * a lead is saved only with the code texted to THAT mobile -- the form is
    public, so a row in the admin list must be a reachable phone;
  * the same mobile twice is one lead, not two calls;
  * a later visit without campaign tags does not wipe the first campaign;
  * the honeypot quietly drops bots without telling them so;
  * opening an account with that mobile marks the lead CONVERTED, and a
    failure there never fails the signup.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

from app.api.v1 import leads_public
from app.api.v1.admin import leads as admin_leads
from app.core.exceptions import ValidationFailedError
from app.models.lead import LeadStatus
from app.services import lead_service as svc
from app.services import sms_service
from app.utils import otp as otp_mod


class FakeRedis:
    def __init__(self):
        self.d: dict = {}

    async def get(self, k):
        return self.d.get(k)

    async def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1
        return self.d[k]

    async def expire(self, k, s):
        return True

    async def delete(self, *ks):
        for k in ks:
            self.d.pop(k, None)

    def pipeline(self):
        r = self

        class P:
            def setex(self, k, ttl, v):
                r.d[k] = v

            def delete(self, k):
                r.d.pop(k, None)

            async def execute(self):
                return []

        return P()


class FakeLead(SimpleNamespace):
    store: dict = {}

    def __init__(self, **kw):
        base = dict(
            id=PydanticObjectId(), status=LeadStatus.NEW, note="", submissions=1,
            converted_user_id=None, converted_at=None, ref_code=None, utm_source=None,
            utm_medium=None, utm_campaign=None, utm_content=None, utm_term=None,
        )
        base.update(kw)
        super().__init__(**base)

    @classmethod
    async def find_one(cls, q):
        return cls.store.get(q["mobile"])

    async def insert(self):
        FakeLead.store[self.mobile] = self

    async def save(self):
        FakeLead.store[self.mobile] = self


@pytest.fixture
def env(monkeypatch):
    r = FakeRedis()
    sent: list[tuple[str, str]] = []
    FakeLead.store = {}
    users: dict = {}

    async def fake_send(mobile, code):
        sent.append((mobile, code))

    async def user_find_one(q):
        return users.get(q["mobile"])

    monkeypatch.setattr(otp_mod, "get_redis", lambda: r)
    monkeypatch.setattr(sms_service, "send_otp", fake_send)
    monkeypatch.setattr(svc, "Lead", FakeLead)
    import app.models.user as um

    monkeypatch.setattr(um.User, "find_one", user_find_one)
    return SimpleNamespace(sent=sent, users=users)


def _run(c):
    return asyncio.run(c)


def _submit(code, **over):
    kw = dict(full_name="Ravi Kumar", mobile="9876543210", city="Indore", otp=code,
              tags={"utm_source": "facebook", "utm_campaign": "diwali", "ref_code": "ab12"})
    kw.update(over)
    return _run(svc.submit(**kw))


def test_a_lead_needs_the_code_texted_to_that_mobile(env):
    _run(svc.send_code("+91 98765 43210"))
    assert env.sent and env.sent[0][0] == "9876543210"
    with pytest.raises(ValidationFailedError):
        _submit("0000" if env.sent[0][1] != "0000" else "1111")
    assert FakeLead.store == {}
    lead = _submit(env.sent[0][1])
    assert lead.mobile == "9876543210"
    assert lead.ref_code == "AB12"
    assert lead.utm_campaign == "diwali"
    assert lead.status == LeadStatus.NEW


def test_a_code_works_once(env):
    _run(svc.send_code("9876543210"))
    code = env.sent[-1][1]
    _submit(code)
    with pytest.raises(ValidationFailedError):
        _submit(code)


def test_a_code_for_another_number_is_refused(env):
    _run(svc.send_code("9876543210"))
    with pytest.raises(ValidationFailedError):
        _submit(env.sent[-1][1], mobile="9123456780")


def test_the_same_mobile_twice_is_one_lead(env):
    _run(svc.send_code("9876543210"))
    _submit(env.sent[-1][1])
    _run(svc.send_code("9876543210"))
    lead = _submit(env.sent[-1][1], city="Bhopal", tags={})
    assert len(FakeLead.store) == 1
    assert lead.submissions == 2
    assert lead.city == "Bhopal"
    # A bare later visit keeps the campaign that first brought them in.
    assert lead.utm_campaign == "diwali"
    assert lead.ref_code == "AB12"


def test_an_invalid_mobile_is_never_texted(env):
    with pytest.raises(ValidationFailedError):
        _run(svc.send_code("12345"))
    assert env.sent == []


def test_name_and_city_are_required(env):
    _run(svc.send_code("9876543210"))
    with pytest.raises(ValidationFailedError):
        _submit(env.sent[-1][1], full_name=" ")
    with pytest.raises(ValidationFailedError):
        _submit(env.sent[-1][1], city="")


def test_tracking_tags_are_cleaned():
    assert svc.clean_tag("<script>alert(1)</script>") == "scriptalert1script"
    assert svc.clean_tag("x" * 500) == "x" * 80
    assert svc.clean_tag("   ") is None


def test_an_existing_customer_is_marked_converted(env):
    uid = PydanticObjectId()
    env.users["9876543210"] = SimpleNamespace(id=uid)
    _run(svc.send_code("9876543210"))
    lead = _submit(env.sent[-1][1])
    assert lead.status == LeadStatus.CONVERTED
    assert lead.converted_user_id == uid


def test_signup_marks_the_lead_converted(env):
    _run(svc.send_code("9876543210"))
    _submit(env.sent[-1][1])
    uid = PydanticObjectId()
    _run(svc.mark_converted("+919876543210", uid))
    lead = FakeLead.store["9876543210"]
    assert lead.status == LeadStatus.CONVERTED
    assert lead.converted_user_id == uid


def test_a_lead_failure_never_fails_signup(monkeypatch):
    class Boom:
        @classmethod
        async def find_one(cls, q):
            raise RuntimeError("db down")

    monkeypatch.setattr(svc, "Lead", Boom)
    _run(svc.mark_converted("9876543210", PydanticObjectId()))  # must not raise


def test_signup_calls_mark_converted():
    from app.api.v1.user import auth

    assert "lead_service.mark_converted(" in inspect.getsource(auth._create_signup_user)


def test_the_honeypot_drops_bots_silently(env, monkeypatch):
    called = []

    async def no_submit(**kw):
        called.append(kw)

    monkeypatch.setattr(svc, "submit", no_submit)
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="1.2.3.4"))
    body = leads_public.LeadSubmit(
        full_name="Bot", mobile="9876543210", city="X", otp="1234", website="http://spam"
    )
    res = _run(leads_public.submit_lead(body, req))
    assert res.data == {"ok": True}
    assert called == []


def test_public_routes_are_rate_limited():
    s = inspect.getsource(leads_public)
    assert s.count('dependencies=[rate_limit("auth")]') == 2


def test_admin_routes_are_super_admin_only():
    for fn in (admin_leads.list_leads, admin_leads.export_leads, admin_leads.update_lead):
        assert "admin: SuperAdmin" in inspect.getsource(fn)


def test_routes_are_mounted():
    import app.main as m

    paths = {getattr(r, "path", "") for r in m.app.routes}
    assert "/api/v1/leads" in paths
    assert "/api/v1/leads/otp" in paths
    assert "/api/v1/admin/leads" in paths
    assert "/api/v1/admin/leads/export.csv" in paths
    assert "/api/v1/admin/leads/{lead_id}" in paths
