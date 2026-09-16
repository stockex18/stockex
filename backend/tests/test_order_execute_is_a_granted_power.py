"""Placing, approving or cancelling someone's order is the super-admin's power.

Operator: "Only the Super Admin should have the power to execute or cancel
orders — no one else. Market Watch ka execute me system rakho, admin ko
permission de super admin taki ve use kar paye."

Market Watch's `place-orders` had no permission dependency at all — any admin
could fire an order into any user in their pool. Approve and force-cancel sat
behind `trading_view`, which every admin with the trading screen already had.
Now all three sit behind `order_execute`: the super-admin passes always, an
admin only where granted, and it is the one admin flag that starts OFF.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.core.dependencies import require_perm
from app.core.exceptions import InsufficientPermissionsError
from app.models.user import AdminPermissions, UserRole


def _check(admin):
    dep = require_perm("order_execute", "write")
    return asyncio.run(dep(admin))


def test_the_flag_is_off_until_it_is_granted():
    fresh = AdminPermissions()
    assert fresh.order_execute is False
    # Nothing else moved — the other defaults are what they were.
    assert fresh.banks is True and fresh.trading_view is False


def test_the_super_admin_never_needs_the_grant():
    sa = SimpleNamespace(role=UserRole.SUPER_ADMIN, admin_permissions=None)
    assert _check(sa) is sa


def test_an_admin_without_the_grant_is_refused():
    a = SimpleNamespace(role=UserRole.ADMIN, admin_permissions=AdminPermissions())
    with pytest.raises(InsufficientPermissionsError):
        _check(a)


def test_an_admin_the_super_admin_granted_it_to_may_execute():
    a = SimpleNamespace(
        role=UserRole.ADMIN, admin_permissions=AdminPermissions(order_execute=True)
    )
    assert _check(a) is a


def test_a_broker_can_never_execute():
    # BrokerPermissions has no such key, so the tri-state lookup reads OFF.
    from app.models.user import BrokerPermissions

    b = SimpleNamespace(
        role=UserRole.BROKER,
        admin_permissions=None,
        broker_permissions=BrokerPermissions(),
    )
    with pytest.raises(InsufficientPermissionsError):
        _check(b)


def test_market_watch_execute_is_gated():
    from app.api.v1.admin import marketwatch

    src = inspect.getsource(marketwatch.place_orders)
    assert 'require_perm("order_execute", "write")' in src


def test_approve_and_cancel_are_gated():
    from app.api.v1.admin import trading

    for fn in (trading.approve_pending_order, trading.force_cancel):
        assert 'require_perm("order_execute", "write")' in inspect.getsource(fn), fn.__name__
