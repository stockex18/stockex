"""An admin can approve a pending order, and it fills straight away.

Operator: pending order ko admin approve kare to wo turant execute ho jaye —
at the user's own limit price (the trigger for an SL-M).
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import trading


def _src() -> str:
    return inspect.getsource(trading.approve_pending_order)


def test_it_fills_at_the_users_limit_then_the_trigger():
    s = _src()
    assert "fill_px = limit_px if limit_px > 0 else trigger_px" in s
    assert "execute_market_order(existing, force_fill_price=fill_px)" in s


def test_only_a_pending_order_can_be_approved():
    s = _src()
    assert "OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIAL" in s
    assert "Only a pending order can be approved" in s


def test_it_takes_the_pollers_claim_so_one_order_fills_once():
    s = _src()
    claim = s.index('idempotency_check_and_set(f"pending_fire:{existing.id}"')
    fill = s.index("execute_market_order(")
    assert claim < fill, "claim before fill, or the poller can fire it too"


def test_the_scope_is_checked_before_anything_moves():
    s = _src()
    assert s.index("assert_user_in_scope(admin, existing.user_id)") < s.index("execute_market_order(")


def test_it_needs_write_permission_and_is_audited():
    s = _src()
    assert 'require_perm("trading_view", "write")' in inspect.getsource(trading)
    assert "AuditAction.ORDER_MODIFY" in s and '"approved": True' in s
