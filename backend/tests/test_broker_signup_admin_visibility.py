"""Two signup lists, kept apart.

One says whose BROKERS a client sees when signing up. The other says which
ADMINS a brand-new broker may sign up under. They used to be the same list —
"one switch rather than two that can disagree" — but the operator wants them
decided separately: an admin can be right for a client to find a broker under
and wrong to hand a fresh broker to.
"""

from __future__ import annotations

import inspect

from app.api.v1.admin import settings as admin_settings
from app.services import broker_search_service as svc


def test_the_two_lists_have_their_own_keys():
    assert svc.HIDDEN_ADMINS_KEY == "broker_search.hidden_admin_ids"
    assert svc.HIDDEN_SIGNUP_ADMINS_KEY == "broker_search.hidden_signup_admin_ids"
    assert svc.HIDDEN_ADMINS_KEY != svc.HIDDEN_SIGNUP_ADMINS_KEY


def test_the_broker_signup_picker_reads_its_own_list():
    src = inspect.getsource(svc.search_admins)
    assert "_hidden_set(HIDDEN_SIGNUP_ADMINS_KEY)" in src


def test_what_a_signup_may_name_matches_that_picker():
    # The list shown and the list accepted must be the same set, or a hidden
    # admin can still be named by hand.
    src = inspect.getsource(svc.resolve_signup_admin)
    assert "_hidden_set(HIDDEN_SIGNUP_ADMINS_KEY)" in src


def test_the_client_side_broker_directory_is_untouched():
    for fn in (svc.search_brokers, svc.resolve_active_visible_broker):
        src = inspect.getsource(fn)
        assert "HIDDEN_SIGNUP_ADMINS_KEY" not in src, fn.__name__
        assert "_hidden_set()" in src, fn.__name__


def test_the_settings_endpoint_serves_both():
    src = inspect.getsource(admin_settings.get_broker_search_hidden)
    assert "hidden_admin_ids" in src and "hidden_signup_admin_ids" in src


def test_a_save_writes_only_the_list_it_was_given():
    """A client that knows one list must not blank the other by omission —
    the same trap that quietly revoked `order_execute`."""
    src = inspect.getsource(admin_settings.set_broker_search_hidden)
    assert "if field not in payload:" in src
    assert "await broker_search_service.get_hidden_admin_ids(key)" in src


def test_a_save_with_neither_list_is_refused():
    src = inspect.getsource(admin_settings.set_broker_search_hidden)
    assert 'if not any(k in payload for k in ("hidden_admin_ids", "hidden_signup_admin_ids")):' in src


def test_only_the_super_admin_may_change_either():
    for fn in (admin_settings.get_broker_search_hidden, admin_settings.set_broker_search_hidden):
        assert "_require_super_admin(admin)" in inspect.getsource(fn), fn.__name__
