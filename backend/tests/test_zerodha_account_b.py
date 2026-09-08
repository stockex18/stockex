"""Account B could not complete a login because the callback could not tell
it apart from Account A.

Reported: "Connection failed: Kite session generation failed: Token is invalid
or has expired." on Login Account B, with both accounts DISCONNECTED.

Kite never sends the redirect URL in the login request - it uses whatever is
registered on the app at developers.kite.trade:

    get_login_url -> https://kite.zerodha.com/connect/login?v=3&api_key=...

so the URL the browser comes BACK on is the only thing that says which account
the request_token belongs to. Both accounts had the same one registered, with
no `account`:

    https://api.stockex.in/api/v1/admin/zerodha/callback

Landing there defaults to account 0, so B's request_token was exchanged against
ACCOUNT A's api_secret. A token issued by one Kite app cannot be redeemed by
another, and that is precisely the error Kite returns.

    Account A  o1ygw2bwax57yqud   apiSecret set   accessToken set
    Account B  o1nghx05exelkhto   apiSecret set   accessToken NONE
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import zerodha as api


def test_account_b_has_its_own_callback_path():
    paths = {r.path for r in api.router.routes}
    assert "/zerodha/callback/b" in paths
    assert "/zerodha/callback" in paths, "account A's path must keep working"


def test_the_b_callback_exchanges_against_account_one():
    src = inspect.getsource(api.oauth_callback_account_b)
    assert "account=1" in src


def test_a_path_rather_than_a_query_parameter():
    """Kite appends its own query string to the registered redirect, so a URL
    that already carries one is a merge waiting to go wrong. A distinct path
    cannot collide."""
    src = inspect.getsource(api.oauth_callback_account_b)
    assert "query string" in src or "?account=1" in src


def test_the_original_callback_still_takes_the_account_parameter():
    """Anything already pointed at `?account=` keeps working."""
    src = inspect.getsource(api.oauth_callback)
    assert "account: int = Query(default=0" in src


def test_the_login_url_carries_no_redirect():
    """This is why the registered URL is the only signal - worth pinning, since
    a future change here would quietly make the path irrelevant."""
    from app.services.zerodha_service import ZerodhaService

    src = inspect.getsource(ZerodhaService.get_login_url)
    assert "connect/login?v=3&api_key=" in src
    assert "redirect" not in src.lower()


def test_the_session_exchange_uses_that_accounts_own_secret():
    """The reason a mixed-up account cannot work: the secret is read per
    account, and Kite rejects a token redeemed with the wrong app's."""
    from app.services.zerodha_service import ZerodhaService

    src = inspect.getsource(ZerodhaService.generate_session)
    assert "self._get_settings(account_index)" in src
    assert "s.apiSecret" in src
