"""An admin could hand out more leverage than the super-admin gave them.

Requirement: "Admin can't grant clients more leverage than what the Super
Admin assigned to the Admin", and the same one step down — a broker can't
exceed their admin.

The clamp for this already existed (`clamp_child_patch`) but was wired into
exactly ONE endpoint: the screen where a tier edits its own pool default. Four
other endpoints write the very same margin fields and had no clamp at all:

    PUT  /netting/user/{user}/{segment}       one client's override
    PUT  /netting/broker/{broker}/segments/   a broker under this admin
    POST /netting/scripts  (+ /bulk)          one symbol, this tier's scope
    PUT  /netting/scripts/{id}

So a 100x admin could still write 500x onto a single client, onto a broker, or
onto one symbol. The cap held only on the screen they were expected to use.

The bound is the actor's OWN effective settings rather than their parent's.
Their own row is already the parent's ceiling clamped into it, so checking
against it makes the rule cascade by itself: super-admin bounds admin, admin
bounds broker, and either bounds any client or symbol beneath them.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.core.exceptions import ValidationFailedError
from app.models.user import UserRole
from app.services import netting_service as ns
from app.api.v1.admin import netting as api


class _Actor:
    def __init__(self, role):
        self.role = role
        self.id = "actor"


def _patch_own(monkeypatch, effective):
    from app.services import settings_snapshot

    async def fake(*, source_user, segment_name):
        return effective

    monkeypatch.setattr(settings_snapshot, "_resolve_effective_segment", fake)


def _run(actor, patch, monkeypatch, own=None):
    _patch_own(monkeypatch, own if own is not None else {"intradayMargin": 100.0,
                                                         "marginCalcMode": "times"})
    return asyncio.run(ns.assert_within_own_ceiling(actor, "MCX_FUT", patch))


# ── the rule ────────────────────────────────────────────────────────────────

def test_more_leverage_than_your_own_is_refused(monkeypatch):
    with pytest.raises(ValidationFailedError) as e:
        _run(_Actor(UserRole.ADMIN), {"intradayMargin": 500.0, "marginCalcMode": "times"}, monkeypatch)
    assert "your own limits" in str(e.value)


def test_the_same_or_less_is_allowed(monkeypatch):
    _run(_Actor(UserRole.ADMIN), {"intradayMargin": 100.0, "marginCalcMode": "times"}, monkeypatch)
    _run(_Actor(UserRole.ADMIN), {"intradayMargin": 40.0, "marginCalcMode": "times"}, monkeypatch)


def test_it_applies_to_a_broker_too(monkeypatch):
    with pytest.raises(ValidationFailedError):
        _run(_Actor(UserRole.BROKER), {"intradayMargin": 101.0, "marginCalcMode": "times"}, monkeypatch)


def test_the_overnight_side_is_bound_as_well(monkeypatch):
    # Carry leverage is where the real overnight exposure sits.
    own = {"overnightMargin": 50.0, "marginCalcMode": "times"}
    with pytest.raises(ValidationFailedError):
        _run(_Actor(UserRole.ADMIN), {"overnightMargin": 200.0, "marginCalcMode": "times"}, monkeypatch, own)


def test_percent_mode_is_bound_from_the_other_direction(monkeypatch):
    # In percent mode a LOWER number is looser, so the bound is a floor.
    own = {"intradayMargin": 10.0, "marginCalcMode": "percent"}
    with pytest.raises(ValidationFailedError):
        _run(_Actor(UserRole.ADMIN), {"intradayMargin": 2.0, "marginCalcMode": "percent"}, monkeypatch, own)


def test_the_super_admin_is_unbounded(monkeypatch):
    # Top of the chain — and clamping the SA is what broke saves before.
    _run(_Actor(UserRole.SUPER_ADMIN), {"intradayMargin": 9999.0, "marginCalcMode": "times"}, monkeypatch)


# ── it must not become a new way to fail ────────────────────────────────────

def test_an_unresolvable_segment_does_not_block_the_save(monkeypatch):
    # Refusing a save because a lookup failed is a worse failure than the one
    # this prevents.
    _run(_Actor(UserRole.ADMIN), {"intradayMargin": 500.0}, monkeypatch, own={})


def test_a_lookup_that_raises_does_not_block_the_save(monkeypatch):
    from app.services import settings_snapshot

    async def boom(*, source_user, segment_name):
        raise RuntimeError("db down")

    monkeypatch.setattr(settings_snapshot, "_resolve_effective_segment", boom)
    asyncio.run(ns.assert_within_own_ceiling(_Actor(UserRole.ADMIN), "MCX_FUT", {"intradayMargin": 500.0}))


def test_an_empty_patch_is_a_no_op(monkeypatch):
    _run(_Actor(UserRole.ADMIN), {}, monkeypatch)


# ── every write path is covered ─────────────────────────────────────────────

def test_all_five_write_paths_call_it():
    src = inspect.getsource(api)
    assert src.count("assert_within_own_ceiling") == 5
    for fn in (
        api.upsert_user_override,
        api.update_broker_segment,
        api.create_script,
        api.create_scripts_bulk,
        api.update_script,
    ):
        assert "assert_within_own_ceiling" in inspect.getsource(fn), fn.__name__


def test_the_pool_default_screen_still_has_its_own_clamp():
    # The one path that was already guarded must stay guarded.
    src = inspect.getsource(api.update_segment)
    assert "clamp_child_patch" in src
