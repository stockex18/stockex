"""Every new broker is asked Male / Female (female clients join female brokers
only), and the order card shows the day's circuit band up top."""

import inspect
import pathlib

import pytest
from pydantic import ValidationError

from app.api.v1.admin import auth as admin_auth
from app.api.v1.admin import brokers as admin_brokers
from app.schemas.admin.brokers import CreateBrokerRequest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = dict(full_name="Ab", email="a@b.co", mobile="9876543210", password="Abcdefg1")


@pytest.mark.parametrize(
    "model, extra",
    [
        (CreateBrokerRequest, {}),
        (admin_auth.BrokerRegisterRequest, {"admin_id": "x", "city": "Mumbai", "pincode": "400001"}),
    ],
)
def test_creating_a_broker_asks_male_or_female(model, extra):
    with pytest.raises(ValidationError):
        model(**BASE, **extra)
    with pytest.raises(ValidationError):
        model(**BASE, **extra, gender="OTHER")
    assert model(**BASE, **extra, gender="FEMALE").gender == "FEMALE"


def test_both_paths_save_it():
    assert "b.gender = payload.gender" in inspect.getsource(admin_brokers.create_broker)
    assert "broker.gender = payload.gender" in inspect.getsource(admin_auth.broker_register)


def test_every_create_form_asks():
    for page in (
        "frontend-admin/app/(admin)/management/brokers/page.tsx",
        "frontend-admin/app/(admin)/management/sub-admins/page.tsx",
        "frontend-admin/app/broker/login/page.tsx",
    ):
        assert "<GenderChoice" in (ROOT / page).read_text(encoding="utf-8"), page


def test_the_order_card_shows_the_circuit_band():
    sheet = (ROOT / "frontend-user/components/trading/TradeDetailSheet.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "frontend-user/components/trading/OrderPanel.tsx").read_text(encoding="utf-8")
    assert "lower={effSettings?.lower_circuit}" in sheet and "upper={effSettings?.upper_circuit}" in sheet
    assert "<CircuitBand" in panel and "upper={upperCircuit}" in panel
