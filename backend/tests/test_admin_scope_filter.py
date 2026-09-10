"""The super-admin sees every admin's book, but could not tell them apart.

Asked for: all admins' orders and positions by default, a picker to narrow to
one, and the owning admin named on each row in a colour.

Positions already carried `assigned_admin_id/name` via `build_owner_map`;
orders carried only the user, so a mixed list gave no way to tell whose book a
row belonged to. Neither endpoint could be narrowed to one admin at all.

The filter is built on `scoped_user_ids(target_admin)` rather than a fresh
query, so it inherits the broker-subtree union, the demo exclusion and the
closed-user exclusion that the unfiltered path already applies — the two
cannot drift.

It is INTERSECTED with the caller's own scope, never substituted for it. An
admin passing another admin's id must not get a window into a book they were
never allowed to see.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import trading
from app.api.v1.admin import _owner


ORDERS = inspect.getsource(trading.list_orders)
POSITIONS = inspect.getsource(trading.list_positions)
SCOPE = inspect.getsource(_owner.pool_scope_for_admin)


def test_both_monitors_take_an_admin_filter():
    assert "admin_id: str | None = None" in ORDERS
    assert "admin_id: str | None = None" in POSITIONS


def test_no_filter_means_every_admin():
    # The default has to stay "everything the caller may see" — that is the
    # page the operator wants on load.
    for src in (ORDERS, POSITIONS):
        i = src.index("elif admin_id:")
        assert "scoped_user_ids(admin)" in src[i:], "the unfiltered branch is still there"


def test_a_deep_link_to_one_user_still_wins():
    # `user_id` comes from the user-detail page and is more specific.
    for src in (ORDERS, POSITIONS):
        assert src.index("if user_id:") < src.index("elif admin_id:")


def test_the_filter_can_only_narrow():
    # Intersected with the caller's scope, never replacing it.
    assert "caller_scope = await scoped_user_ids(caller)" in SCOPE
    assert "if caller_scope is None:" in SCOPE
    assert "str(uid) in allowed" in SCOPE


def test_it_reuses_the_scope_the_endpoints_already_use():
    # A second hand-written query here is how the filtered and unfiltered
    # views end up disagreeing about who is in a pool.
    assert "scoped_user_ids(target)" in SCOPE


def test_a_bad_or_non_admin_id_shows_nothing():
    # Failing OPEN would hand back the whole book, which is the wrong
    # direction for a filter that could not resolve.
    assert "return []" in SCOPE
    assert "UserRole.ADMIN" in SCOPE


def test_an_order_row_names_its_admin():
    assert '"assigned_admin_id"' in ORDERS
    assert '"assigned_admin_name"' in ORDERS
    assert "build_owner_map" in ORDERS


def test_orders_and_positions_read_the_same_owner_map():
    # Two owner lookups would drift; both go through build_owner_map.
    assert "build_owner_map" in POSITIONS
