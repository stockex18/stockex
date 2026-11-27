"""Overnight premium charge (crypto): amount, side and daily cut-off."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.netting import NettingFieldsBase, NettingFieldsRequired
from app.models.position import Position
from app.models.user import User
from app.services import market_data_service, netting_service, wallet_router, wallet_service
from app.services import premium_charge_service as pc
from app.utils.time_utils import IST


def _s(kind="percentage", value=0.5, on="both"):
    return {"premium_type": kind, "premium_charge": value, "premium_on": on}


# ── Amount ────────────────────────────────────────────────────────────
def test_percentage_of_position_value_in_rupees():
    # 2 BTC at $60,000, USD/INR 85, 0.1 % → 2 × 60000 × 85 × 0.001 = 10,200
    amt = pc.premium_amount(quantity=2, price=60000, settings=_s(value=0.1), fx=85)
    assert amt == Decimal("10200.00")


def test_fixed_is_rupees_per_unit():
    assert pc.premium_amount(quantity=-3, price=60000, settings=_s("fixed", 50), fx=85) == Decimal("150.00")
    assert pc.premium_amount(quantity=0.5, price=1, settings=_s("fixed", 50)) == Decimal("25.00")


def test_side_choice():
    assert pc.premium_amount(quantity=1, price=100, settings=_s(on="buy")) > 0
    assert pc.premium_amount(quantity=-1, price=100, settings=_s(on="buy")) == 0
    assert pc.premium_amount(quantity=-1, price=100, settings=_s(on="sell")) > 0
    assert pc.premium_amount(quantity=1, price=100, settings=_s(on="sell")) == 0
    assert pc.premium_amount(quantity=-1, price=100, settings=_s(on="both")) > 0


def test_off_when_zero():
    assert pc.premium_amount(quantity=1, price=100, settings=_s(value=0)) == 0
    assert pc.premium_amount(quantity=0, price=100, settings=_s()) == 0


def test_new_premium_fields_default_off():
    req = NettingFieldsRequired()
    assert (req.premiumType, req.premiumCharge, req.premiumOn, req.premiumTime) == ("percentage", 0.0, "both", "22:30")
    assert NettingFieldsBase(premiumType="FIXED", premiumOn="SELL").premiumOn == "sell"


# ── When it is due ────────────────────────────────────────────────────
NOW = datetime(2026, 11, 26, 23, 0, tzinfo=IST)


def test_due_only_after_the_cutoff_for_positions_open_before_it():
    cut = pc.cutoff_today("22:30", NOW)
    assert cut == datetime(2026, 11, 26, 22, 30, tzinfo=IST)
    assert pc.is_due(datetime(2026, 11, 25, 10, 0, tzinfo=IST), cut, NOW)       # carried from yesterday
    assert pc.is_due(datetime(2026, 11, 26, 9, 0, tzinfo=IST), cut, NOW)        # opened earlier today
    assert not pc.is_due(datetime(2026, 11, 26, 22, 45, tzinfo=IST), cut, NOW)  # opened after the cut-off
    assert not pc.is_due(datetime(2026, 11, 25, 10, 0, tzinfo=IST), cut, cut - timedelta(minutes=1))


def test_naive_opened_at_is_utc():
    cut = pc.cutoff_today("22:30", NOW)
    # 16:45 UTC naive = 22:15 IST → before the cut-off
    assert pc.is_due(datetime(2026, 11, 26, 16, 45), cut, NOW)
    # 17:15 UTC = 22:45 IST → after it
    assert not pc.is_due(datetime(2026, 11, 26, 17, 15), cut, NOW)
    assert pc.is_due(datetime(2026, 11, 26, 16, 45, tzinfo=UTC), cut, NOW)


def test_bad_time_is_ignored():
    assert pc.cutoff_today("nonsense", NOW) is None


# ── Money: user debited, SA credited, once a day ──────────────────────
class _Coll:
    def __init__(self):
        self.claimed: set[str] = set()

    async def update_one(self, flt, upd):
        day = upd["$set"]["last_premium_charge_day"]
        key = f"{flt['_id']}:{day}"
        hit = key not in self.claimed
        self.claimed.add(key)
        return SimpleNamespace(modified_count=1 if hit else 0)


@pytest.fixture
def money(monkeypatch):
    moves = []
    coll = _Coll()

    async def eff(*a, **k):
        return {"settings": {"premium_type": "fixed", "premium_charge": 10, "premium_on": "both", "premium_time": "22:30"}}

    async def u_adjust(uid, seg, amt, **k):
        moves.append(("user", uid, amt, k["transaction_type"].value))

    async def sa_adjust(uid, amt, **k):
        moves.append(("sa", uid, amt, k["transaction_type"].value))

    async def get_user(uid):
        return SimpleNamespace(user_code="CL1", is_demo=uid == "demo")

    monkeypatch.setattr(netting_service, "get_effective_settings", eff)
    monkeypatch.setattr(wallet_router, "adjust", u_adjust)
    monkeypatch.setattr(wallet_service, "adjust", sa_adjust)
    monkeypatch.setattr(User, "get", get_user)
    monkeypatch.setattr(Position, "get_motor_collection", lambda: coll)
    monkeypatch.setattr(market_data_service, "is_usd_quoted_segment", lambda s: True)
    monkeypatch.setattr(market_data_service, "get_usd_inr_rate", lambda: 85.0)
    return moves


def _pos(uid="u1", qty=-4.0):
    return SimpleNamespace(
        id="p1", user_id=uid, quantity=qty, is_demo=False, product_type="MIS",
        opened_at=datetime(2026, 11, 25, 12, 0, tzinfo=IST), created_at=None,
        ltp=Decimal("60000"), avg_price=Decimal("59000"),
        instrument=SimpleNamespace(segment="CRYPTO", symbol="BTCUSD"),
    )


async def test_user_pays_sa_receives_once_a_day(money):
    assert await pc.charge_position(_pos(), NOW, "sa") == Decimal("40.00")
    assert money == [("user", "u1", Decimal("-40.00"), "PREMIUM_CHARGE"),
                     ("sa", "sa", Decimal("40.00"), "PREMIUM_CHARGE")]
    assert await pc.charge_position(_pos(), NOW, "sa") == 0  # same day: claimed
    assert len(money) == 2


async def test_demo_money_never_reaches_the_sa(money):
    assert await pc.charge_position(_pos(uid="demo"), NOW, "sa") == Decimal("40.00")
    assert [m[0] for m in money] == ["user"]


async def test_nothing_before_the_cutoff(money):
    assert await pc.charge_position(_pos(), NOW.replace(hour=22, minute=0), "sa") == 0
    assert money == []


# ── Super-admin only ──────────────────────────────────────────────────
def test_only_the_super_admin_can_save_premium_fields():
    patch = {"premiumCharge": 5, "premiumType": "fixed", "premiumOn": "buy", "premiumTime": "23:00", "commission": 10}
    netting_service.strip_premium_fields(SimpleNamespace(role="ADMIN"), patch)
    assert patch == {"commission": 10}
    patch = {"premiumCharge": 5, "premiumTime": "23:00"}
    netting_service.strip_premium_fields(SimpleNamespace(role="SUPER_ADMIN"), patch)
    assert patch == {"premiumCharge": 5, "premiumTime": "23:00"}


def test_premium_comes_only_from_a_row_that_sets_it():
    admin_row = NettingFieldsBase(premiumType="fixed", premiumTime="09:00")  # no charge set
    sa_row = NettingFieldsBase(premiumCharge=0.2, premiumOn="buy", premiumTime="23:00")
    out = netting_service.apply_premium_group(NettingFieldsBase(), [None, admin_row, sa_row])
    assert (out.premiumCharge, out.premiumOn, out.premiumTime) == (0.2, "buy", "23:00")
    assert out.premiumType is None  # falls back to the base segment, not the admin row
    # No premium anywhere → nothing from the admin row survives either.
    out = netting_service.apply_premium_group(NettingFieldsBase(premiumTime="09:00"), [admin_row])
    assert out.premiumTime is None and out.premiumType is None
    assert netting_service.apply_premium_group(None, [None]) is None


# ── Instrument-wise rules ─────────────────────────────────────────────
_ADM = "adm1"
_RULES = {
    (None, "CRYPTO", "BTCUSD"): {"premium_type": "fixed", "premium_charge": 2, "premium_on": "both", "premium_time": "22:30"},
    (_ADM, "CRYPTO", "BTCUSD"): {"premium_type": "fixed", "premium_charge": 7, "premium_on": "both", "premium_time": "22:30"},
    (None, "CRYPTO", "ETHUSD"): {"premium_type": "fixed", "premium_charge": 3, "premium_on": "buy", "premium_time": "22:30"},
}


def test_admin_rule_beats_platform_rule_beats_segment():
    assert pc.rule_for(_RULES, _ADM, "CRYPTO", "btcusd")["premium_charge"] == 7
    assert pc.rule_for(_RULES, "other", "CRYPTO", "BTCUSD")["premium_charge"] == 2
    assert pc.rule_for(_RULES, None, "CRYPTO", "BTCUSD")["premium_charge"] == 2
    assert pc.rule_for(_RULES, _ADM, "CRYPTO", "SOLUSD") is None  # → segment premium
    assert pc.rule_for(_RULES, _ADM, "CRYPTO_OPT", "BTCUSD") is None


async def test_an_instrument_rule_replaces_the_segment_premium(money, monkeypatch):
    async def get_user(uid):
        return SimpleNamespace(user_code="CL1", is_demo=False, assigned_admin_id=_ADM)

    monkeypatch.setattr(User, "get", get_user)
    # Segment says ₹10/unit; the admin's BTCUSD rule says ₹7/unit → 4 × 7.
    assert await pc.charge_position(_pos(), NOW, "sa", _RULES) == Decimal("28.00")


async def test_an_instrument_rule_keeps_its_own_side(money):
    p = _pos(qty=-4.0)
    p.instrument = SimpleNamespace(segment="CRYPTO", symbol="ETHUSD")
    # ETHUSD is Buy only; this is a short → nothing, even though the segment charges both sides.
    assert await pc.charge_position(p, NOW, "sa", _RULES) == 0
    assert money == []
