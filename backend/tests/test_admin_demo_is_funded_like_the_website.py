"""A demo account is a demo account however it was opened.

Operator: "if admin demo create kare tab bhi same balance rahe — exactly like
the website." The website's Try-Demo gives 🪙5,00,000 in main and 🪙1,00,000
in each of the four segment wallets and the games wallet. One created by hand
in the admin panel got a flat 🪙1,00,000 in main and nothing anywhere else —
so it could not place a single trade, because trading reads the segment
wallets, not main.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import users as admin_users
from app.services import demo_service


def test_the_figures_live_in_one_place():
    assert demo_service.DEMO_MAIN_TARGET == 500000
    assert demo_service.DEMO_WALLET_SHARE == 100000


def test_the_admin_path_uses_the_same_helper():
    s = inspect.getsource(admin_users)
    assert "demo_service.ensure_demo_funding(" in s
    assert "if payload.is_demo:" in s


def test_the_flat_one_lakh_default_is_gone():
    """`payload.initial_balance or (100_000 if payload.is_demo else 0)` was the
    whole bug — main only, and nothing to trade with."""
    s = inspect.getsource(admin_users)
    assert "100_000 if payload.is_demo" not in s
    assert "initial_bal = payload.initial_balance or 0" in s


def test_an_explicit_opening_balance_still_works_on_top():
    s = inspect.getsource(admin_users)
    assert s.index("ensure_demo_funding(") < s.index("initial_bal = payload.initial_balance")


def test_a_live_account_still_draws_on_the_admin_float():
    """The demo branch must not have taken the float guard with it."""
    s = inspect.getsource(admin_users)
    assert "debit_admin_float_for_user(" in s
    assert "if not payload.is_demo:" in s


def test_funding_only_ever_adds():
    """Called on every demo login and on the daily reset, so it must top up
    rather than overwrite — otherwise a demo user's profits vanish."""
    s = inspect.getsource(demo_service.ensure_demo_funding)
    assert "if have < DEMO_WALLET_SHARE:" in s
    assert "max(zero, DEMO_MAIN_TARGET - main_have)" in s


def test_every_door_into_a_demo_account_goes_through_it():
    from app.api.v1.user import auth as user_auth
    from app.services import auth_service

    assert "ensure_demo_funding(" in inspect.getsource(user_auth)      # website signup
    assert "ensure_demo_funding(" in inspect.getsource(auth_service)   # shared Try-Demo
    assert "ensure_demo_funding(" in inspect.getsource(admin_users)    # admin panel
    assert "ensure_demo_funding(" in inspect.getsource(demo_service)   # daily reset
