"""The super-admin's client ledger was empty because they own no client.

`_pool_clause` gives the super-admin `{"assigned_admin_id": None}` — the
clients sitting under no admin. Live, every one of the 32 clients belongs to
one of the four admins, so that scope resolved to nobody: the master ledger
came back `total: 0` and opening one client's history 403'd with "User is
assigned to a sub-admin". Operator: "Suddenly client ledger history it's not
show."

Commit 70e80db taught the Orders and Positions monitors to opt out of the pool
clause via `sees_every_book`. The ledger is the same kind of screen.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import ledger


def _src() -> str:
    return inspect.getsource(ledger.list_all)


def test_the_whole_ledger_is_not_narrowed_for_the_super_admin():
    s = _src()
    # The pool scope is only computed when the caller is NOT the super-admin.
    assert "elif not sees_every_book(admin):" in s
    assert s.index("sees_every_book(admin)") < s.index("scoped_user_ids(admin)")


def test_one_client_history_opens_for_the_super_admin():
    s = _src()
    scope_check = s.index("assert_user_in_scope(admin, user_id)")
    guard = s.index("if not sees_every_book(admin):")
    assert guard < scope_check, "the scope check has to sit under the guard"


def test_an_admin_is_still_held_to_their_own_pool():
    s = _src()
    # Both narrowing paths survive for everyone else.
    assert "assert_user_in_scope(admin, user_id)" in s
    assert 'q["user_id"] = {"$in": scope}' in s


def test_only_the_super_admin_sees_every_book():
    from types import SimpleNamespace

    from app.core.dependencies import sees_every_book
    from app.models.user import UserRole

    assert sees_every_book(SimpleNamespace(role=UserRole.SUPER_ADMIN)) is True
    for role in (UserRole.ADMIN, UserRole.BROKER, UserRole.CLIENT):
        assert sees_every_book(SimpleNamespace(role=role)) is False
