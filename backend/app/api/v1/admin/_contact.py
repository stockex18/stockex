"""Whose client's phone number is it.

A broker's client belongs to the broker's relationship, not to the admin
above them. The admin still sees the account, its code, its book and its
money — everything needed to run risk — but not the contact details, so the
client cannot be approached around the broker.

The super admin sees everything, and a broker sees their own subtree (scope
checks already keep them inside it).
"""

from __future__ import annotations

from typing import Any

from app.models.user import UserRole


def contact_hidden_from(viewer: Any, u: Any) -> bool:
    role = getattr(viewer, "role", None)
    if role == UserRole.SUPER_ADMIN:
        return False
    if not getattr(u, "assigned_broker_id", None):
        return False
    return role != UserRole.BROKER


def mask_contact(row: dict, viewer: Any, u: Any) -> dict:
    """Blank the contact fields in an already-built row, in place."""
    if contact_hidden_from(viewer, u):
        row["email"] = None
        row["mobile"] = None
        row["contact_hidden"] = True
    return row
