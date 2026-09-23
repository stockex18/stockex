"""The super-admin's Users page is the whole platform, not "their pool".

`_pool_clause` gives the super-admin `{assigned_admin_id: None}` — the clients
sitting under NO admin. Every client belongs to an admin, so that resolves to
nothing: the page said "0 users" while 12 existed under one admin.

The same trap was found and fixed for Orders, Positions and the Ledger; the
Users list never got the opt-out. It has it now.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import users as admin_users
from app.core import dependencies as deps


def test_the_list_lets_the_super_admin_out_of_the_pool():
    s = inspect.getsource(admin_users.list_users)
    assert "scope = {} if sees_every_book(admin) else await scoped_user_filter(admin)" in s


def test_the_live_stats_behind_the_same_page_agree():
    """Two more scoped queries feed the balance / P&L columns. If they keep
    the pool clause the rows appear with every number blank."""
    s = inspect.getsource(admin_users)
    assert s.count("if not sees_every_book(admin):") == 2
    assert s.count("scope_query.update(await scoped_user_filter(admin))") == 2


def test_an_admin_is_still_held_to_their_own_pool():
    """The opt-out is for the super-admin alone — an admin must never see
    another admin's clients."""
    s = inspect.getsource(deps.sees_every_book)
    assert "SUPER_ADMIN" in s


def test_the_role_filter_still_hides_admin_rows():
    """Widening the scope must not start leaking admin/broker rows onto the
    trading-users page."""
    s = inspect.getsource(admin_users.list_users)
    assert "UserRole.SUPER_ADMIN.value," in s
    assert '"$nin"' in s


def test_closed_users_are_still_hidden_by_default():
    s = inspect.getsource(admin_users.list_users)
    assert 'query["status"] = {"$ne": UserStatus.CLOSED.value}' in s


def test_deleting_a_user_stays_super_admin_only():
    """Destructive, and the UI gate is only a gate — the server decides."""
    s = inspect.getsource(admin_users.delete_user)
    assert "admin.role != UserRole.SUPER_ADMIN" in s
    assert "Only the super admin can delete users" in s
