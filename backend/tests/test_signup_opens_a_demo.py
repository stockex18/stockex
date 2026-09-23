"""Filling the signup form opens a DEMO account, not a real one.

Operator: "register par direct real account open mat ho — demo hi bane, login
ho jaye, aur jab wo switch kare tab real account banke admin ko dikhe."

Nobody becomes a real client of somebody's book by filling a form. They try
the platform on virtual money, and turn real deliberately — and THAT is the
moment the owning admin is told, because it is the first moment there is
anything for them to act on.
"""

from __future__ import annotations

import inspect

from app.api.v1.user import auth as user_auth
from app.api.v1.user import profile as user_profile


def test_registering_no_longer_opens_a_real_account():
    s = inspect.getsource(user_auth.register)
    assert "is_demo=False" not in s
    assert "Please log in" not in s


def test_it_goes_through_the_demo_path_itself():
    """Enforced on the server, so a stale app build or a direct call to this
    endpoint cannot open a real account either."""
    s = inspect.getsource(user_auth.register)
    assert "return await demo_register(payload, request)" in s


def test_it_hands_back_a_session_rather_than_asking_them_to_log_in():
    src = inspect.getsource(user_auth)
    block = src[src.index('    "/register",'):]
    assert "response_model=APIResponse[TokenPair]" in block[:300]


def test_the_demo_route_still_funds_and_logs_in():
    s = inspect.getsource(user_auth.demo_register)
    assert "is_demo=True" in s
    assert "ensure_demo_funding(" in s
    assert "mint_login_pair(" in s


def test_converting_is_still_the_only_way_to_become_real():
    s = inspect.getsource(user_profile.convert_to_real)
    assert 'if not getattr(user, "is_demo", False):' in s
    assert "convert_demo_to_real(user)" in s


def test_the_owning_admin_is_told_when_somebody_turns_real():
    s = inspect.getsource(user_profile.convert_to_real)
    assert "notification_service.create_for_admins(" in s
    assert "AdminNotificationEventType.USER_REGISTERED" in s
    # Deep-links to that user so the admin can act on it.
    assert 'link=f"/users?q={fresh.user_code}"' in s


def test_the_notification_is_raised_only_after_the_conversion_succeeded():
    s = inspect.getsource(user_profile.convert_to_real)
    assert s.index("convert_demo_to_real(user)") < s.index("create_for_admins(")


def test_a_failed_bell_row_never_undoes_a_real_account():
    s = inspect.getsource(user_profile.convert_to_real)
    assert "convert_to_real_notify_failed" in s
    tail = s[s.index("create_for_admins("):]
    assert "except Exception" in tail
