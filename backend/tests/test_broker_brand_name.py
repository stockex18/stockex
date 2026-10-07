"""A broker has a brand name, and clients see it when choosing who to join.

"Broker Brand name — profile section me, broker create karte waqt bhi, aur
jab user register kare to use wahi brand name dikhe."

Three places a brand has to be settable — the broker's own profile, the
broker's self-signup, and the admin's create-broker form — and one place it
has to be shown: the client choosing a broker.

It is a NEW field, `broker_brand_name`, and not the existing `brand_name`. That
one is the ADMIN white-label: the name and logo a whole platform wears on a
custom domain, gated by BRANDING_ENABLED, read by the PDF reports as their
header. Reusing it would have changed a broker's report header the day they
typed one, and tied a plain display name to a feature flag that governs
something else entirely. The tests below pin that the two stay apart.
"""

from __future__ import annotations

import inspect
import pathlib

from app.api.v1.admin import auth as admin_auth
from app.api.v1.admin import brokers as admin_brokers
from app.api.v1.admin import me as admin_me
from app.api.v1.user import profile as user_profile
from app.models.user import User
from app.schemas.admin.brokers import BrokerDTO, CreateBrokerRequest
from app.services import broker_management_service as bsvc
from app.services import broker_search_service as search

_REPO = pathlib.Path(__file__).resolve().parents[2]


def _fe(*parts: str) -> str:
    return (_REPO.joinpath(*parts)).read_text(encoding="utf-8", errors="ignore")


# ── the field, and that it is not the white-label one ────────────────
def test_a_broker_has_a_brand_name_field():
    assert "broker_brand_name" in User.model_fields


def test_it_is_not_the_admin_white_label_field():
    """Two different things that happen to share a word."""
    assert "brand_name" in User.model_fields
    assert "broker_brand_name" in User.model_fields
    assert User.model_fields["broker_brand_name"] is not User.model_fields["brand_name"]


def test_the_white_label_code_is_untouched():
    """The PDF header and the admin dashboard read `brand_name`. A broker's
    brand must never reach them."""
    from app.api.v1 import branding as public_branding
    from app.api.v1.admin import reports as admin_reports
    from app.services import branding_service

    for mod in (admin_reports, branding_service, public_branding):
        assert "broker_brand_name" not in inspect.getsource(mod), mod.__name__


# ── set when creating a broker ───────────────────────────────────────
def test_the_create_request_accepts_a_brand_name():
    f = CreateBrokerRequest.model_fields["brand_name"]
    assert f.default is None  # optional


def test_the_brand_name_has_a_length_cap():
    meta = CreateBrokerRequest.model_fields["brand_name"].metadata
    assert any(getattr(m, "max_length", None) == 64 for m in meta)


def test_the_service_stores_it_trimmed_and_empty_means_none():
    """A blank string stored as the brand would read as a brand and hide the
    broker's real name in the picker."""
    src = inspect.getsource(bsvc.create_broker)
    assert "brand_name: str | None = None" in src
    assert '(brand_name or "").strip() or None' in src


def test_the_router_passes_it_through():
    assert "brand_name=payload.brand_name" in inspect.getsource(admin_brokers.create_broker)


def test_the_broker_list_returns_it():
    assert "brand_name" in BrokerDTO.model_fields
    assert 'getattr(b, "broker_brand_name", None)' in inspect.getsource(admin_brokers._ser_broker)


# ── set at self-signup ───────────────────────────────────────────────
def test_self_signup_accepts_and_stores_it():
    assert "brand_name" in admin_auth.BrokerRegisterRequest.model_fields
    src = inspect.getsource(admin_auth.broker_register)
    assert 'broker.broker_brand_name = (payload.brand_name or "").strip() or None' in src


# ── set from the broker's own profile ────────────────────────────────
def test_the_profile_reads_and_writes_it():
    assert '"brand_name": getattr(admin, "broker_brand_name", None)' in inspect.getsource(admin_me.my_profile)
    src = inspect.getsource(admin_me.update_my_profile)
    assert 'if "brand_name" in payload' in src
    assert "user.broker_brand_name = brand or None" in src


def test_an_overlong_brand_is_refused_not_truncated():
    src = inspect.getsource(admin_me.update_my_profile)
    assert "len(brand) > 64" in src
    assert "status_code=400" in src


def test_an_omitted_brand_leaves_the_stored_one_alone():
    """The profile save sends only the fields it has; `if "brand_name" in
    payload` is what stops a city-only save from wiping the brand."""
    src = inspect.getsource(admin_me.update_my_profile)
    assert src.index('if "brand_name" in payload') < src.index("user.broker_brand_name")


# ── shown to the client ──────────────────────────────────────────────
def test_the_broker_search_returns_it():
    assert '"brand_name": getattr(r, "broker_brand_name", None)' in inspect.getsource(search.search_brokers)


def test_a_client_can_search_by_brand():
    """They know a broker by the name they trade under."""
    assert "broker_brand_name" in search.SEARCH_FIELDS["all"]


def test_city_and_pin_modes_do_not_match_on_brand():
    """Those modes mean "this field", and nothing else."""
    assert "broker_brand_name" not in search.SEARCH_FIELDS["city"]
    assert "broker_brand_name" not in search.SEARCH_FIELDS["pincode"]


def test_the_clients_own_broker_block_carries_it():
    assert '"brand_name": getattr(b, "broker_brand_name", None)' in inspect.getsource(user_profile)


# ── the front ends ───────────────────────────────────────────────────
def test_the_picker_shows_the_brand_first_and_the_name_second():
    s = _fe("frontend-user", "components", "common", "BrokerPicker.tsx")
    assert "brokerTitle(b)" in s
    u = _fe("frontend-user", "lib", "utils.ts")
    assert "brand || name" in u
    # The person's name is kept as a second line ONLY when a brand replaced it.
    assert "brand && name && brand !== name" in u


def test_the_register_and_profile_pages_use_the_same_rule():
    for page in (("app", "(auth)", "register", "page.tsx"), ("app", "(dashboard)", "profile", "page.tsx")):
        assert "brokerTitle(" in _fe("frontend-user", *page), page


def test_the_admin_can_set_it_in_all_three_places():
    assert "brand_name" in _fe("frontend-admin", "app", "(admin)", "management", "brokers", "page.tsx")
    assert "brand_name" in _fe("frontend-admin", "app", "broker", "login", "page.tsx")
    assert "brand_name" in _fe("frontend-admin", "app", "(admin)", "settings", "platform", "page.tsx")


def test_the_broker_list_highlights_it():
    s = _fe("frontend-admin", "app", "(admin)", "management", "brokers", "page.tsx")
    assert 'header: "Brand"' in s
