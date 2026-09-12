"""A broker's client's phone number belongs to the broker.

Operator: "broker ke user ko sirf broker ko hi uske number dikhe, admin na
dekh paye." The admin above the broker still sees the account, its code and
its book — everything risk needs — but not the contact, so the client cannot
be approached around the broker.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.admin._contact import contact_hidden_from, mask_contact
from app.models.user import UserRole

BROKER_ID = "b1"


def _client(broker=BROKER_ID):
    return SimpleNamespace(assigned_broker_id=broker, mobile="9990001111", email="c@x.com")


def _viewer(role):
    return SimpleNamespace(role=role)


def test_admin_cannot_see_a_brokers_client_contact():
    assert contact_hidden_from(_viewer(UserRole.ADMIN), _client()) is True


def test_the_broker_still_sees_it():
    assert contact_hidden_from(_viewer(UserRole.BROKER), _client()) is False


def test_the_super_admin_still_sees_it():
    assert contact_hidden_from(_viewer(UserRole.SUPER_ADMIN), _client()) is False


def test_an_admins_own_client_is_untouched():
    # No broker in between — this is the admin's own relationship.
    assert contact_hidden_from(_viewer(UserRole.ADMIN), _client(broker=None)) is False


def test_masking_blanks_both_fields_and_flags_the_row():
    u = _client()
    row = mask_contact({"mobile": u.mobile, "email": u.email, "user_code": "CL1"}, _viewer(UserRole.ADMIN), u)
    assert row["mobile"] is None and row["email"] is None
    assert row["contact_hidden"] is True
    # Everything else the admin needs is still there.
    assert row["user_code"] == "CL1"


def test_masking_leaves_a_visible_row_alone():
    u = _client()
    row = mask_contact({"mobile": u.mobile, "email": u.email}, _viewer(UserRole.BROKER), u)
    assert row["mobile"] == "9990001111"
    assert "contact_hidden" not in row
