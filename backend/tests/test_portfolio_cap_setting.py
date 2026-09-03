"""The aggregate leverage cap has to be visible to whoever it constrains.

It lived only in the backend config as a hardcoded 33.33 for NSE/BSE, and
appeared nowhere in the admin panel. An admin who had set 50x per-instrument
margin had no way to discover why orders were being refused at 33.33x — two
rules that contradict each other, with only one of them on screen.

It reads from a platform setting now, with the config value as the fallback.
The failure modes worth pinning: an unreadable value must not silently become
"no limit", and both readers must agree — a cap only half the system obeys is
worse than no cap.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import portfolio_cap as pc


@pytest.fixture(autouse=True)
def _clean():
    pc.invalidate()
    yield
    pc.invalidate()


class _Row:
    def __init__(self, v):
        self.setting_value = v


def _stub(monkeypatch, values: dict):
    """Serve `values` as if they were rows in platform_settings."""

    class _PS:
        @staticmethod
        async def find_one(q):
            key = q["setting_key"]
            return _Row(values[key]) if key in values else None

    import app.models.platform_setting as mod

    monkeypatch.setattr(mod, "PlatformSetting", _PS)


# ── the keys ──────────────────────────────────────────────────────────
def test_the_key_matches_what_the_admin_card_writes():
    assert pc.setting_key("NSE_BSE") == "portfolio.max_leverage.NSE_BSE"


def test_the_category_falls_out_of_the_dotted_prefix():
    """The generic upsert files a new key under its prefix, which is how the
    card's `platformList("portfolio")` finds it."""
    assert pc.KEY_PREFIX.split(".", 1)[0] == "portfolio"


def test_every_wallet_kind_config_defines_is_covered():
    from app.core.config import settings as cfg

    assert set(pc.WALLET_KINDS) == set(cfg.portfolio_leverage_caps)


# ── fallback ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_with_no_setting_the_config_value_wins():
    from app.core.config import settings as cfg

    assert await pc.caps() == pytest.approx(cfg.portfolio_leverage_caps)


@pytest.mark.asyncio
async def test_a_database_failure_falls_back_to_config(monkeypatch):
    """Not to zero. Zero means NO LIMIT — a blip must never quietly remove the
    cap on every wallet."""
    import app.models.platform_setting as mod

    class _Boom:
        @staticmethod
        async def find_one(_):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(mod, "PlatformSetting", _Boom)
    from app.core.config import settings as cfg

    assert await pc.caps() == pytest.approx(cfg.portfolio_leverage_caps)


@pytest.mark.asyncio
async def test_an_unreadable_value_falls_back_rather_than_disabling(monkeypatch):
    """A typo'd cap must not read as "no limit"."""
    from app.core.config import settings as cfg

    _stub(monkeypatch, {"portfolio.max_leverage.NSE_BSE": "fifty"})
    got = await pc.caps()
    assert got["NSE_BSE"] == pytest.approx(cfg.portfolio_leverage_caps["NSE_BSE"])


@pytest.mark.asyncio
async def test_a_negative_value_is_ignored(monkeypatch):
    """It would block every order rather than allow a very small one."""
    from app.core.config import settings as cfg

    _stub(monkeypatch, {"portfolio.max_leverage.NSE_BSE": -5})
    got = await pc.caps()
    assert got["NSE_BSE"] == pytest.approx(cfg.portfolio_leverage_caps["NSE_BSE"])


# ── the setting wins when it is valid ─────────────────────────────────
@pytest.mark.asyncio
async def test_the_admin_value_overrides_the_config(monkeypatch):
    _stub(monkeypatch, {"portfolio.max_leverage.NSE_BSE": 50})
    assert (await pc.caps())["NSE_BSE"] == 50.0


@pytest.mark.asyncio
async def test_zero_really_does_mean_no_limit(monkeypatch):
    """Both readers treat `> 0` as "a cap exists", so zero must survive the
    round trip as zero and not be mistaken for unset."""
    _stub(monkeypatch, {"portfolio.max_leverage.NSE_BSE": 0})
    assert (await pc.caps())["NSE_BSE"] == 0.0
    assert await pc.cap_for("NSE_BSE") == 0.0


# ── both readers agree ────────────────────────────────────────────────
def test_the_order_gate_reads_it_here():
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    assert "_pcap.cap_for(_cap_kind)" in src
    assert "portfolio_leverage_caps" not in src


def test_the_risk_enforcer_reads_the_same_source():
    """A cap the admin can see but only half the system obeys is worse than no
    cap at all."""
    from app.services import risk_enforcer

    src = inspect.getsource(risk_enforcer._enforce_for_user)
    assert "_pcap.cap_for(_pc_kind)" in src
    assert "_cfg_pc.portfolio_leverage_caps" not in src


def test_a_cap_of_zero_switches_both_off():
    """Each reader guards on `> 0`, so zero disables it rather than capping at
    nothing."""
    from app.services import order_validator, risk_enforcer

    assert "if _cap_lev > 0:" in inspect.getsource(order_validator.validate)
    assert "if _pc_lev > 0:" in inspect.getsource(risk_enforcer._enforce_for_user)


def test_the_cache_can_be_dropped_after_an_edit():
    assert callable(pc.invalidate)
    assert pc._TTL <= 60, "an admin edit should take effect within a minute"
