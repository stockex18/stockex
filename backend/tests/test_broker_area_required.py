"""A broker's city and PIN code are required — they are all the client-side
signup picker's City and PIN modes match on.

Found in a check of those two modes: the search logic worked, but the only
active broker had neither field set, so both modes found nobody. "Optional,
fill it in later from Settings" in practice meant never. Now:

    * the broker signup refuses to register without them;
    * the profile page lets a broker change them but not blank them;
    * a broker missing either sees a banner asking for it (frontend);
    * the client picker shows a failed search as an error, not "no brokers".
"""

from __future__ import annotations

import inspect
import pathlib

import pytest
from pydantic import ValidationError

from app.api.v1.admin import auth as admin_auth
from app.api.v1.admin import me as admin_me

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = {
    "full_name": "Ab", "email": "a@b.co", "mobile": "9876543210", "password": "Abcdefg1",
    "admin_id": "x", "gender": "MALE",
}


def test_signup_without_city_or_pin_is_refused():
    with pytest.raises(ValidationError):
        admin_auth.BrokerRegisterRequest(**BASE)
    with pytest.raises(ValidationError):
        admin_auth.BrokerRegisterRequest(**BASE, city="Mumbai")
    with pytest.raises(ValidationError):
        admin_auth.BrokerRegisterRequest(**BASE, pincode="400001")


@pytest.mark.parametrize("pin", ["", "12345", "012345", "40000a", "4000011"])
def test_signup_refuses_a_junk_pin(pin):
    with pytest.raises(ValidationError):
        admin_auth.BrokerRegisterRequest(**BASE, city="Mumbai", pincode=pin)


def test_signup_accepts_both():
    r = admin_auth.BrokerRegisterRequest(**BASE, city="Mumbai", pincode="400001")
    assert (r.city, r.pincode) == ("Mumbai", "400001")


def test_place_is_checked_before_the_account_is_created():
    """A refusal after `create_broker` would leave a half-made broker behind."""
    src = inspect.getsource(admin_auth.broker_register)
    assert src.index('raise ValidationFailedError("Enter your city.")') < src.index("bsvc.create_broker(")
    assert src.index("is_valid_pincode(_pin)") < src.index("bsvc.create_broker(")


def test_a_broker_cannot_blank_city_or_pin_from_the_profile():
    src = inspect.getsource(admin_me.update_my_profile)
    assert "if is_broker and not city:" in src
    assert "if is_broker and not pin:" in src


def test_the_broker_signup_form_requires_both():
    page = (ROOT / "frontend-admin/app/broker/login/page.tsx").read_text(encoding="utf-8")
    assert '"City (optional)"' not in page
    assert '"PIN code (optional)"' not in page
    assert 'city: z.string().trim().min(2' in page


def test_a_broker_missing_either_is_reminded():
    layout = (ROOT / "frontend-admin/app/(admin)/layout.tsx").read_text(encoding="utf-8")
    assert "<BrokerAreaBanner />" in layout


def test_a_failed_search_is_not_shown_as_no_brokers():
    picker = (ROOT / "frontend-user/components/common/BrokerPicker.tsx").read_text(encoding="utf-8")
    assert "isError" in picker
    assert "RATE_LIMIT_EXCEEDED" in picker
    assert "!isLoading && !isError && brokers.length === 0" in picker


def test_a_miss_in_one_list_shows_matches_from_the_other():
    """No male broker at a PIN but a female one is: say "No male brokers
    found", then list her — a client may join either."""
    picker = (ROOT / "frontend-user/components/common/BrokerPicker.tsx").read_text(encoding="utf-8")
    assert 'list === "FEMALE" ? "MALE" : "FEMALE"' in picker
    assert "enabled: !!otherList && !!debounced" in picker
    assert 'No {pink ? "female" : "male"} brokers found for' in picker
    # Only exact matches cross over, never the other list's "nearest".
    assert "(otherData || []).filter((b) => !b.nearby)" in picker
