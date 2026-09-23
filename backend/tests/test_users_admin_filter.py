"""Show one admin's users, or everybody's.

The super-admin's Users page lists the whole platform. Asked for: a picker
beside the status filter — "All admins", or one of them.

The subtlety is which clause to filter with. The ready-made pool helpers
(`scoped_user_ids`, `pool_scope_for_admin`) bundle `is_demo: {"$ne": True}`,
so reusing one would have emptied the Demo tab the moment a filter was picked.
This endpoint already applies its own role / status / demo conditions, so it
needs the assignment half alone.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import users as admin_users
from app.core import dependencies as deps


def _src() -> str:
    return inspect.getsource(admin_users.list_users)


def test_the_endpoint_takes_an_admin_id():
    assert "admin_id: str | None = None," in _src()


def test_it_uses_the_assignment_clause_only():
    """`_admin_pool_clause` carries no role / status / demo opinion — which is
    exactly why the Demo tab keeps working with a filter applied."""
    s = _src()
    assert "_admin_pool_clause(target.id)" in s
    assert "scoped_user_ids" not in s
    assert "pool_scope_for_admin" not in s


def test_the_helper_really_is_opinion_free():
    s = inspect.getsource(deps._admin_pool_clause)
    assert "no role / status conditions" in s
    assert "is_demo" not in s


def test_the_pool_helpers_would_have_broken_the_demo_tab():
    """Guards the reason for the choice above."""
    assert 'is_demo": {"$ne": True}' in inspect.getsource(deps.scoped_user_ids)


def test_it_narrows_and_never_widens():
    """An admin passing another admin's id must not see a book they were never
    allowed to see — the filter is ANDed onto the caller's own scope."""
    s = _src()
    assert "and_clauses.append(await _admin_pool_clause(target.id))" in s
    assert s.index("scope = {} if sees_every_book(admin)") < s.index("if admin_id:")


def test_an_id_that_is_not_an_admin_filters_to_nothing():
    """The safe direction for a filter that failed to resolve is an empty
    page, not the whole book."""
    s = _src()
    assert 'and_clauses.append({"_id": None})' in s
    assert "UserRole.SUPER_ADMIN," in s and "UserRole.BROKER," in s


def test_a_malformed_id_does_not_500():
    s = _src()
    assert "except Exception:" in s
    assert "target = None" in s
