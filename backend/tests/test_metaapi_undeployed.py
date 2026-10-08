"""Gold and silver sat at 0 because the MetaApi account was UNDEPLOYED.

The service tried to deploy it on every reconnect, but the configured token has
no account-management rights (ForbiddenException on deployAccount). That
failure was a debug line, so nothing said why, and the loop retried every 30 s.
Now it says so and backs off to UNDEPLOYED_RETRY_SEC.
"""

import asyncio
import sys
import types

import pytest

from app.services import metaapi_service as ms


class FakeAccount:
    def __init__(self, state, deploy_error=None, deploys_to=None):
        self.state = state
        self._deploy_error = deploy_error
        self._deploys_to = deploys_to
        self.deploy_calls = 0

    async def deploy(self):
        self.deploy_calls += 1
        if self._deploy_error:
            raise self._deploy_error
        self._pending = self._deploys_to

    async def reload(self):
        if getattr(self, "_pending", None):
            self.state = self._pending

    async def wait_connected(self):
        raise RuntimeError("stop here")  # the test only cares about the deploy step


def _fake_sdk(monkeypatch, account):
    class MetaApi:
        def __init__(self, *a, **k):
            async def get_account(_id):
                return account

            self.metatrader_account_api = types.SimpleNamespace(get_account=get_account)

    monkeypatch.setitem(sys.modules, "metaapi_cloud_sdk", types.SimpleNamespace(MetaApi=MetaApi))


def test_an_account_that_cannot_be_deployed_says_why(monkeypatch):
    forbidden = Exception("You do not have access to ...:deployAccount method")
    acc = FakeAccount("UNDEPLOYED", deploy_error=forbidden)
    _fake_sdk(monkeypatch, acc)
    with pytest.raises(ms.AccountUndeployedError) as e:
        asyncio.run(ms.MetaApiService()._connect_and_poll())
    assert acc.deploy_calls == 1
    assert "UNDEPLOYED" in str(e.value)
    assert "deployAccount" in str(e.value)       # the real reason, not a guess
    assert "app.metaapi.cloud" in str(e.value)   # and what to do about it


def test_a_deployable_account_goes_on_to_connect(monkeypatch):
    acc = FakeAccount("UNDEPLOYED", deploys_to="DEPLOYING")
    _fake_sdk(monkeypatch, acc)
    svc = ms.MetaApiService()
    # wait_connected is swallowed by the service; the streaming connection is
    # the next thing it reaches for, which this fake does not have.
    with pytest.raises(AttributeError):
        asyncio.run(svc._connect_and_poll())
    assert acc.deploy_calls == 1
    assert acc.state == "DEPLOYING"


def test_a_deployed_account_is_not_redeployed(monkeypatch):
    acc = FakeAccount("DEPLOYED")
    _fake_sdk(monkeypatch, acc)
    with pytest.raises(AttributeError):
        asyncio.run(ms.MetaApiService()._connect_and_poll())
    assert acc.deploy_calls == 0


def test_an_undeployed_account_is_retried_in_minutes_not_every_30_seconds(monkeypatch):
    svc = ms.MetaApiService()
    sleeps = []

    async def undeployed():
        raise ms.AccountUndeployedError("MetaApi account is UNDEPLOYED")

    async def fake_sleep(sec):
        sleeps.append(sec)
        svc._stop = True

    monkeypatch.setattr(svc, "_connect_and_poll", undeployed)
    monkeypatch.setattr(ms.asyncio, "sleep", fake_sleep)
    asyncio.run(svc._run_loop())
    assert sleeps == [ms.UNDEPLOYED_RETRY_SEC]
    assert ms.UNDEPLOYED_RETRY_SEC >= 300
    assert "UNDEPLOYED" in svc.status()["lastError"]
