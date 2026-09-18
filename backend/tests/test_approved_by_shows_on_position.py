"""A hand-approved pending order says so on the position it opened.

Operator: "if ye position super admin ne approve karke ki hai to position me
highlight dikhe, pop me reason dikhe" — so the approver is stamped on the
order at approval time and carried onto the blotter row.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import trading
from app.models.order import Order


def test_the_order_can_remember_who_approved_it():
    for f in ("approved_by_id", "approved_by_role", "approved_by_name", "approved_at"):
        assert f in Order.model_fields, f
        assert Order.model_fields[f].default is None, f"{f} must default to unstamped"


def test_the_stamp_lands_before_the_fill_saves_the_order():
    s = inspect.getsource(trading.approve_pending_order)
    stamp = s.index("existing.approved_by_role = ")
    assert s.index('idempotency_check_and_set(f"pending_fire:') < stamp < s.index(
        "execute_market_order("
    ), "stamp after the claim, before the fill — the engine's save persists it"
    assert "existing.approved_by_name = admin.full_name or admin.user_code" in s


def test_an_untouched_order_carries_no_stamp():
    o = Order.model_construct()
    assert o.approved_by_role is None and o.approved_at is None


def test_the_blotter_row_carries_the_approver():
    s = inspect.getsource(trading.list_positions)
    assert '"approved_by": _approved_for(r)' in s
    # Only orders that were actually approved go into the lookup; everything
    # else must render a plain row.
    assert 'if getattr(o, "approved_by_role", None)' in s
    assert '"at": o.approved_at.isoformat() if o.approved_at else None' in s


def test_it_walks_the_same_fills_as_the_order_type_column():
    """Both helpers must agree on which fill opened the position, or a row
    could show LIMIT from one order and an approver from another."""
    a = inspect.getsource(trading.list_positions)
    body = a[a.index("def _approved_for("):]
    for step in ("bucket = _bucket_for(p)", "if getattr(t, \"pnl_inr\", None) is not None:"):
        assert step in body, step
