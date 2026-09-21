"""A deleted admin's money still says whose it was.

Deleting an admin removes the User but not their security ledger, so the
Security Money list had nothing to print but a raw ObjectId next to a real
balance — one of them sitting at MINUS 63,317. Two guards:

  • the code and name are stamped on the row while the account exists, so it
    can always be read afterwards;
  • the account cannot be deleted at all while the money is still open.
"""

from __future__ import annotations

import inspect

from app.models.admin_security import AdminSecurity
from app.services import admin_management_service, admin_security_service


def test_the_row_can_carry_who_it_belongs_to():
    for f in ("admin_code", "admin_name"):
        assert f in AdminSecurity.model_fields, f
        assert AdminSecurity.model_fields[f].default == ""


def test_the_stamp_costs_one_lookup_per_admin_not_one_per_trade():
    s = inspect.getsource(admin_security_service.get_or_create)
    assert "return row if row.admin_code else await _stamp_identity(row)" in s


def test_a_label_never_breaks_the_money():
    s = inspect.getsource(admin_security_service._stamp_identity)
    assert "except Exception" in s and "logger.debug" in s


def test_the_list_prints_the_name_and_flags_the_deletion():
    s = inspect.getsource(admin_security_service.list_all)
    assert 'code = u.user_code if u else (r.admin_code or "")' in s
    assert '"is_deleted": u is None' in s
    # The raw id survives only as the last resort, never as the first choice.
    assert 'r.admin_name or code' in s


def test_an_admin_holding_money_cannot_be_deleted():
    s = inspect.getsource(admin_management_service.delete_sub_admin)
    assert "AdminSecurity.admin_id == sa.id" in s
    assert "if held != 0 or owed != 0:" in s
    assert "ValidationFailedError" in s
    # And the check comes BEFORE anything is reassigned or removed —
    # a refusal after half the unwind has run is not a refusal.
    assert s.index("held != 0 or owed != 0") < s.index("update_many(")
    assert s.index("held != 0 or owed != 0") < s.index("await sa.delete()")
