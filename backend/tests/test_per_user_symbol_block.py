"""Per-user symbol blocks (Segment Settings → Users → "Script (per-symbol)
overrides"). Bug fixed 25 Nov 2026.

Reported: Upendra Sharma blocked NIFTY for a user (CSL01, CL24268538) and the
user could no longer see ANY instrument with "nifty" in its name, BANKNIFTY
included. Two bugs together:

1. `inactive_admin_rows` read the per-symbol row (NSE_IDX_FUT / "NIFTY" / No)
   as a segment-wide one and hid the whole Index Future segment.
2. The row was saved as the bare word "NIFTY" and compared with full contract
   symbols, so it never matched NIFTY26DECFUT — the intended block did nothing.
"""

from __future__ import annotations

import pytest
from beanie import init_beanie
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from app.models.netting import (
    BrokerSegmentOverride,
    NettingScriptOverride,
    NettingSegment,
    SubAdminSegmentOverride,
    SuperAdminSegmentOverride,
    UserSegmentOverride,
)
from app.models.user import User, UserRole
from app.services import netting_service as ns


# ── The matching rule ─────────────────────────────────────────────────
def test_an_underlying_covers_its_own_contracts_only():
    fut = ("FUT",)
    assert ns.is_contract_of_underlying("NIFTY26DECFUT", "NIFTY", fut)
    assert not ns.is_contract_of_underlying("NIFTYNXT5026DECFUT", "NIFTY", fut)
    assert not ns.is_contract_of_underlying("BANKNIFTY26DECFUT", "NIFTY", fut)
    assert not ns.is_contract_of_underlying("NIFTY26DEC25500CE", "NIFTY", fut)
    assert ns.is_contract_of_underlying("NIFTY2612225500PE", "NIFTY", ("CE", "PE"))  # weekly
    assert ns.is_contract_of_underlying("GOLD26DECFUT", "GOLD", fut)
    assert not ns.is_contract_of_underlying("GOLDM26DECFUT", "GOLD", fut)
    assert not ns.is_contract_of_underlying("NIFTY", "NIFTY", fut)


def test_only_digit_free_symbols_on_fno_rows_are_underlyings():
    assert ns._user_row_underlying("NSE_IDX_FUT", "nifty") == "NIFTY"
    assert ns._user_row_underlying("NSE_IDX_FUT", "NIFTY26DECFUT") is None  # a contract
    assert ns._user_row_underlying("NSE_EQ", "RELIANCE") is None  # cash: exact match
    assert ns._user_row_underlying("CRYPTO", "BTCUSD") is None


# ── Against a database ────────────────────────────────────────────────
@pytest.fixture
async def user(monkeypatch):
    await init_beanie(
        database=AsyncMongoMockClient()["per_user_symbol_block"],
        document_models=[NettingSegment, NettingScriptOverride, UserSegmentOverride,
                         SubAdminSegmentOverride, SuperAdminSegmentOverride,
                         BrokerSegmentOverride, User],
    )

    async def no_cache(*_a, **_k):
        return None

    async def no_super_admin():
        return None

    monkeypatch.setattr(ns, "cache_get", no_cache)
    monkeypatch.setattr(ns, "cache_set", no_cache)
    monkeypatch.setattr(ns, "_resolve_super_admin_id", no_super_admin)
    u = User(email="csl@x.local", mobile="9000000001", password_hash="x", full_name="CSL01",
             role=UserRole.CLIENT, user_code="CL1")
    await u.insert()
    # Index Future switched ON for this user (as CSL01 has it).
    await UserSegmentOverride(user_id=u.id, segment_name="NSE_IDX_FUT",
                              isActive=True, tradingEnabled=True).insert()
    return u


async def _block(u, seg, sym, active=False):
    await UserSegmentOverride(user_id=u.id, segment_name=seg, symbol=sym,
                              isActive=active, tradingEnabled=active).insert()


async def test_a_symbol_block_no_longer_hides_the_whole_segment(user):
    await _block(user, "NSE_IDX_FUT", "NIFTY")
    assert "NSE_IDX_FUT" not in await ns.inactive_admin_rows(user_id=user.id)


async def test_a_segment_wide_block_still_hides_the_segment(user):
    await UserSegmentOverride(user_id=user.id, segment_name="NSE_STK_FUT",
                              isActive=False, tradingEnabled=False).insert()
    assert "NSE_STK_FUT" in await ns.inactive_admin_rows(user_id=user.id)


async def test_blocking_nifty_hides_nifty_futures_and_nothing_else(user):
    await _block(user, "NSE_IDX_FUT", "NIFTY")
    b = await ns.get_user_blocked_symbols(user.id)
    hidden = {s for s in ("NIFTY26DECFUT", "NIFTY27JANFUT", "BANKNIFTY26DECFUT",
                          "FINNIFTY26DECFUT", "NIFTYNXT5026DECFUT", "NIFTY26DEC25500CE")
              if ns.is_symbol_blocked_for(s, b)}
    assert hidden == {"NIFTY26DECFUT", "NIFTY27JANFUT"}


async def test_an_options_row_covers_calls_and_puts_not_futures(user):
    await _block(user, "NSE_IDX_OPT", "BANKNIFTY")
    b = await ns.get_user_blocked_symbols(user.id)
    assert ns.is_symbol_blocked_for("BANKNIFTY26DEC55000CE", b)
    assert ns.is_symbol_blocked_for("BANKNIFTY26DEC55000PE", b)
    assert not ns.is_symbol_blocked_for("BANKNIFTY26DECFUT", b)


async def test_a_contract_row_and_a_cash_row_still_match_exactly(user):
    await _block(user, "NSE_IDX_FUT", "NIFTY27JANFUT")
    await _block(user, "NSE_EQ", "RELIANCE")
    b = await ns.get_user_blocked_symbols(user.id)
    assert ns.is_symbol_blocked_for("NIFTY27JANFUT", b)
    assert not ns.is_symbol_blocked_for("NIFTY26DECFUT", b)
    assert ns.is_symbol_blocked_for("RELIANCE", b)
    assert not ns.is_symbol_blocked_for("RELIANCE26DECFUT", b)  # cash block stays cash


async def test_a_user_allow_beats_a_platform_pattern_block(user):
    await NettingScriptOverride(segment_id=ObjectId(), segment_name="NSE_IDX_FUT", symbol="NIFTYFUT",
                                isActive=False, tradingEnabled=False).insert()
    await _block(user, "NSE_IDX_FUT", "NIFTY", active=True)
    b = await ns.get_user_blocked_symbols(user.id)
    assert not ns.is_symbol_blocked_for("NIFTY26DECFUT", b)


async def test_orders_find_the_underlying_row(user):
    await _block(user, "NSE_IDX_FUT", "NIFTY")
    row = await ns._user_symbol_override(user.id, "NSE_IDX_FUT", "NIFTY26DECFUT")
    assert row is not None and row.symbol == "NIFTY" and row.tradingEnabled is False
    assert await ns._user_symbol_override(user.id, "NSE_IDX_FUT", "BANKNIFTY26DECFUT") is None
    assert await ns._user_symbol_override(user.id, "NSE_IDX_FUT", "NIFTYNXT5026DECFUT") is None


async def test_an_exact_contract_row_wins_over_the_underlying_row(user):
    await _block(user, "NSE_IDX_FUT", "NIFTY")
    await _block(user, "NSE_IDX_FUT", "NIFTY26DECFUT", active=True)
    row = await ns._user_symbol_override(user.id, "NSE_IDX_FUT", "NIFTY26DECFUT")
    assert row.symbol == "NIFTY26DECFUT" and row.tradingEnabled is True


async def test_no_symbol_keeps_the_old_behaviour(user):
    # Callers without a symbol used to get the segment-wide row back.
    row = await ns._user_symbol_override(user.id, "NSE_IDX_FUT", None)
    assert row is not None and row.symbol is None


# ── Scripts-tab patterns (platform / admin / broker rows) ─────────────
# Same bug class, fixed the same day: `NIFTYFUT` used to match anything that
# started with NIFTY and ended in FUT, so it also blocked NIFTYNXT50; GOLDFUT
# blocked GOLDM, SENSEXFUT blocked SENSEX50.
@pytest.mark.parametrize(
    ("contract", "base", "suffix", "hit"),
    [
        ("NIFTY26DECFUT", "NIFTY", "FUT", True),
        ("NIFTY27JANFUT", "NIFTY", "FUT", True),
        ("NIFTYNXT5026DECFUT", "NIFTY", "FUT", False),
        ("BANKNIFTY26DECFUT", "NIFTY", "FUT", False),
        ("NIFTY26DEC25500CE", "NIFTY", "CE", True),
        ("NIFTY2612225500CE", "NIFTY", "CE", True),  # weekly
        ("NIFTY26DEC25500CE", "NIFTY", "PE", False),
        ("GOLD26DECFUT", "GOLD", "FUT", True),
        ("GOLDM26DECFUT", "GOLD", "FUT", False),
        ("GOLDPETAL26DECFUT", "GOLD", "FUT", False),
        ("SILVER26DECFUT", "SILVER", "FUT", True),
        ("SILVERMIC26NOVFUT", "SILVER", "FUT", False),
        ("CRUDEOILM26DECFUT", "CRUDEOIL", "FUT", False),
        ("SENSEX26DECFUT", "SENSEX", "FUT", True),
        ("SENSEX5026DECFUT", "SENSEX", "FUT", False),  # a digit follows, but not an expiry
    ],
)
def test_a_scripts_tab_pattern_covers_one_underlying(contract, base, suffix, hit):
    assert ns._instrument_matches_pattern(contract, base, suffix) is hit


def test_patterns_are_read_only_on_fno_rows_with_their_own_ending():
    assert ns._script_pattern("NSE_IDX_FUT", "NIFTYFUT") == ("NIFTY", "FUT")
    assert ns._script_pattern("NSE_IDX_OPT", "NIFTYCE") == ("NIFTY", "CE")
    assert ns._script_pattern("MCX_FUT", "GOLDFUT") == ("GOLD", "FUT")
    # A cash stock that happens to end in CE is an exact row, not RELIAN+CE.
    assert ns._script_pattern("NSE_EQ", "RELIANCE") is None
    # A futures row cannot hold an options pattern, and vice versa.
    assert ns._script_pattern("NSE_IDX_FUT", "NIFTYCE") is None
    assert ns._script_pattern("NSE_IDX_OPT", "NIFTYFUT") is None
    # Contract rows stay exact.
    assert ns._script_pattern("NSE_IDX_FUT", "NIFTY26DECFUT") is None


async def test_scripts_tab_blocks_reach_search_correctly(user):
    for seg, sym in (("NSE_IDX_FUT", "NIFTYFUT"), ("MCX_FUT", "GOLDFUT"), ("NSE_EQ", "RELIANCE")):
        await NettingScriptOverride(segment_id=ObjectId(), segment_name=seg, symbol=sym,
                                    isActive=False, tradingEnabled=False).insert()
    b = await ns.get_user_blocked_symbols(user.id)
    blocked = {s for s in ("NIFTY26DECFUT", "NIFTYNXT5026DECFUT", "BANKNIFTY26DECFUT",
                           "GOLD26DECFUT", "GOLDM26DECFUT", "RELIANCE", "RELIANCE26DEC1500CE")
               if ns.is_symbol_blocked_for(s, b)}
    assert blocked == {"NIFTY26DECFUT", "GOLD26DECFUT", "RELIANCE"}


async def test_orders_match_a_scripts_tab_pattern_for_one_underlying(user):
    await NettingScriptOverride(segment_id=ObjectId(), segment_name="NSE_IDX_FUT", symbol="NIFTYFUT",
                                isActive=False, tradingEnabled=False).insert()
    assert (await ns._match_pattern_script("NSE_IDX_FUT", "NIFTY26DECFUT")) is not None
    assert (await ns._match_pattern_script("NSE_IDX_FUT", "NIFTYNXT5026DECFUT")) is None
