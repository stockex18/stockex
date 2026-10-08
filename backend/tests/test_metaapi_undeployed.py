"""Gold and silver sat at 0 because the MetaApi account was UNDEPLOYED.

The service tried to deploy it on every reconnect, but the configured token has
no account-management rights (ForbiddenException on deployAccount). That
failure was a debug line, so nothing said why, and the loop retried every 30 s.

Worse, every refused deploy spent the MetaApi user's deployAccount quota (125 /
10 min) — the same quota the dashboard's Deploy button uses — and the operator
was told "allows 125 requests per 10m" when deploying by hand. So the service
never deploys now: it says the account is undeployed, and waits.
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


@pytest.mark.parametrize("state", ["UNDEPLOYED", "UNDEPLOYING", "DEPLOY_FAILED", "CREATED"])
def test_an_undeployed_account_says_so_and_is_never_deployed_by_the_app(monkeypatch, state):
    acc = FakeAccount(state)
    _fake_sdk(monkeypatch, acc)
    with pytest.raises(ms.AccountUndeployedError) as e:
        asyncio.run(ms.MetaApiService()._connect_and_poll())
    assert acc.deploy_calls == 0                 # the quota is the operator's
    assert state in str(e.value)
    assert "app.metaapi.cloud" in str(e.value)   # and what to do about it


def test_an_account_being_deployed_goes_on_to_connect(monkeypatch):
    acc = FakeAccount("DEPLOYING")
    _fake_sdk(monkeypatch, acc)
    # wait_connected is swallowed by the service; the streaming connection is
    # the next thing it reaches for, which this fake does not have.
    with pytest.raises(AttributeError):
        asyncio.run(ms.MetaApiService()._connect_and_poll())
    assert acc.deploy_calls == 0


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
