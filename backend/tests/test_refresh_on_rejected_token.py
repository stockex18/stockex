"""A token the server just refused must never be sent again.

Reported as "the broker panel keeps logging out". Measured on production: the
refresh endpoint never failed (15/15 OK that day) and every refresh token was
still alive in Redis — yet one phone fired ~4,000 admin requests in five
minutes, every one a 401, until the user signed out and back in by hand (eight
re-logins that morning). On a 401 the client asked for a "fresh" token, and if
its OWN clock said the current one was not expiring it handed the same dead
token back without refreshing. A device clock running behind, or any refusal
that is not expiry, left the panel stuck on 401s.

Now the refused token is passed in and never returned; a refresh is forced
unless a sibling tab has already swapped in a different token. Logout also
sends the access token it held, so the server actually revokes the session.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_admin_app_never_reuses_a_refused_token():
    s = _src("frontend-admin/lib/api.ts")
    assert "export async function ensureFreshAccessToken(rejected?: string | null)" in s
    assert "if (current && current !== rejected && !isExpiringSoon(current, 30)) return current;" in s
    # The 401 path passes the token it sent, and forces a second ask if an
    # in-flight refresh resolved to that same dead token.
    on401 = s[s.index("if (status === 401 && original && !original._retry)") :][:900]
    assert "ensureFreshAccessToken(sent)" in on401
    assert "if (newToken && newToken === sent) newToken = await ensureFreshAccessToken(sent);" in on401


def test_the_user_app_has_the_same_rule():
    s = _src("frontend-user/lib/api.ts")
    assert "export async function ensureFreshAccessToken(rejected?: string | null)" in s
    assert "if (current && current !== rejected && !isExpiringSoon(current, 30)) return current;" in s
    on401 = s[s.index("if (status === 401 && original && !original._retry)") :][:900]
    assert "ensureFreshAccessToken(sent)" in on401


def test_admin_logout_reaches_the_server_with_a_token():
    store = _src("frontend-admin/stores/authStore.ts")
    logout = store[store.index("logout: async () => {") :][:2500]
    # The access token is read BEFORE local storage is cleared…
    assert logout.index("STORAGE_KEYS.accessToken") < logout.index("clearTokens();")
    # …and handed to the API call, which sends it explicitly.
    assert "AdminAuthAPI.logout(refresh, access)" in logout
    api = _src("frontend-admin/lib/api.ts")
    assert 'access ? { headers: { Authorization: `Bearer ${access}` } } : undefined' in api
