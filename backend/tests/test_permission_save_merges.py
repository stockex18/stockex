"""A permission save changes what it was asked to change, and nothing else.

16 Sep: the super-admin granted `order_execute` twice from the sub-admin
screen. Both saves returned 200 and the flag never left False — the tab still
had the bundle from before that checkbox existed, so it sent the thirteen keys
it knew, pydantic filled the fourteenth with its default, and the straight
assignment wrote that default over the grant. The admin then got 403 on
Approve and it looked as if the permission itself was broken.

Operator: "super admin ne admin ko permission nahi diya tab thik, but de diya
to ve work nahi karta."
"""

from __future__ import annotations

import inspect

from app.models.user import AdminPermissions, BrokerPermissions
from app.services import admin_management_service, broker_management_service


def test_a_key_the_client_never_sent_is_left_alone():
    # What a stale page sends: every key it knows, and not the new one.
    stale = AdminPermissions(**{k: True for k in AdminPermissions.model_fields
                                if k != "order_execute"})
    assert stale.order_execute is False, "the default is what overwrote the grant"
    assert "order_execute" not in stale.model_fields_set

    stored = AdminPermissions(order_execute=True).model_dump()
    sent = {k: getattr(stale, k) for k in stale.model_fields_set}
    merged = AdminPermissions(**{**stored, **sent})
    assert merged.order_execute is True, "the grant survived the stale save"
    assert merged.users is True, "and what the page did send still applied"


def test_a_key_the_client_did_send_is_applied():
    # Turning it back OFF must still work — the key is present, value False.
    off = AdminPermissions(order_execute=False)
    assert "order_execute" in off.model_fields_set
    sent = {k: getattr(off, k) for k in off.model_fields_set}
    merged = AdminPermissions(**{**AdminPermissions(order_execute=True).model_dump(), **sent})
    assert merged.order_execute is False


def test_the_admin_service_merges_rather_than_replaces():
    src = inspect.getsource(admin_management_service.update_permissions)
    assert "model_fields_set" in src
    assert "sa.admin_permissions = permissions" not in src, "still a straight replace"
    assert "{**base, **sent}" in src


def test_the_broker_service_merges_too():
    src = inspect.getsource(broker_management_service.update_broker_permissions)
    assert "model_fields_set" in src
    assert "{**base, **sent}" in src


def test_the_broker_cap_is_checked_on_what_will_actually_be_stored():
    # Merge first, validate second — otherwise a merged-in key could slip past
    # the parent's cap.
    src = inspect.getsource(broker_management_service.update_broker_permissions)
    assert src.index("{**base, **sent}") < src.index("_validate_permissions_against_cap(")


def test_a_broker_key_the_client_omitted_survives():
    stale = BrokerPermissions()  # nothing set at all
    assert stale.model_fields_set == set()
    stored = BrokerPermissions(users="EDIT").model_dump()
    sent = {k: getattr(stale, k) for k in stale.model_fields_set}
    merged = BrokerPermissions(**{**stored, **sent})
    assert str(merged.users) == "EDIT"
