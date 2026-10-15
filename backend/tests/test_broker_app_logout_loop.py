"""The broker app reloaded itself and "logged out" over and over.

Measured on production (15 Oct, 11:13-11:14 UTC): one phone hit /build-version
80 times in two minutes, each time opening /broker/login?source=app, jumping
to the dashboard and firing every admin API with NO token (no refresh call at
all) — all 401. Two causes:

1. A rejected refresh cleared the tokens but not the persisted signed-in state
   (`nb.admin.auth`). The broker login page saw a "signed-in broker", sent them
   to the dashboard, which 401'd and sent them back to the login: a reload
   loop that never showed the sign-in form.
2. Expired demo brokers are deleted after 7 days with their app still signed
   in; refresh answered 404, the app took that for a network blip, kept the
   dead token and sat on a wall of 401s. Refresh now says 401 for a missing
   account, and the app treats 404 as signed-out too.
"""

import asyncio
import pathlib

import pytest
from bson import ObjectId

from app.core.exceptions import TokenInvalidError
from app.services import auth_service as auth

ROOT = pathlib.Path(__file__).resolve().parents[2] / "frontend-admin"


def test_a_refresh_for_a_deleted_account_is_a_401_not_a_404(monkeypatch):
    uid = str(ObjectId())

    async def nobody(_):
        return None

    async def live_record(key):
        return {"user_id": uid}

    monkeypatch.setattr(auth, "decode_token", lambda t, expected_type: {"sub": uid, "jti": "j1"})
    monkeypatch.setattr(auth, "cache_get", live_record)
    monkeypatch.setattr(auth, "get_redis", object)
    monkeypatch.setattr(auth.User, "get", nobody)
    with pytest.raises(TokenInvalidError) as e:
        asyncio.run(auth.refresh_tokens("whatever"))
    assert "no longer exists" in str(e.value)


def test_signing_out_clears_the_signed_in_state_with_the_tokens():
    api = (ROOT / "lib/api.ts").read_text(encoding="utf-8")
    clear = api[api.index("export function clearTokens()") :][:900]
    assert "STORAGE_KEYS.authState" in clear
    consts = (ROOT / "lib/constants.ts").read_text(encoding="utf-8")
    assert 'authState: "nb.admin.auth"' in consts
    store = (ROOT / "stores/authStore.ts").read_text(encoding="utf-8")
    assert "name: STORAGE_KEYS.authState," in store  # the SAME key


def test_a_gone_account_is_signed_out_not_retried():
    api = (ROOT / "lib/api.ts").read_text(encoding="utf-8")
    assert "if (status === 401 || status === 403 || status === 404) {" in api


def test_the_broker_login_only_skips_the_form_with_a_real_session():
    page = (ROOT / "app/broker/login/page.tsx").read_text(encoding="utf-8")
    effect = page[page.index('String(admin.role).toUpperCase() !== "BROKER") return;') :][:400]
    assert 'if (hasSession()) router.replace("/dashboard");' in effect
    assert "else void logout();" in effect


def test_the_panel_signs_out_a_tokenless_session_instead_of_firing_401s():
    layout = (ROOT / "app/(admin)/layout.tsx").read_text(encoding="utf-8")
    assert "else if (hydrated && admin && !hasSession()) void logout();" in layout
