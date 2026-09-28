"""A switch the super admin turned off cannot be turned back on below it.

Segment limits have always been clamped to the parent tier, but only the
NUMBERS were. Every switch fell through: `isActive`, `tradingEnabled` and
`allowOvernight` sat in `_CLAMP_SKIP` by name, and the rest were skipped
anyway because `_is_num` rejects bools. So a super admin could disable a
segment for an admin and the admin could re-enable it from their own page.

Operator, 28 Sept: "supar admin no kiya hai to admin yes nahi kar paye."

Both directions matter. A permission (trading allowed) is held DOWN by the
parent; a restriction (exit-only) is held UP. Guard one and not the other and
the hole is the same size -- the admin just turns the parent's block off
instead of turning a permission on.
"""

from __future__ import annotations

import pytest

from app.services.netting_service import clamp_child_patch


@pytest.mark.parametrize(
    "flag", sorted({"isActive", "tradingEnabled", "optionBuyTradingEnabled",
                    "optionSellTradingEnabled", "allowOvernight"})
)
def test_a_permission_the_parent_turned_off_cannot_be_turned_on(flag):
    out, notes = clamp_child_patch({flag: True}, {flag: False})
    assert out[flag] is False
    assert notes and "super-admin" in notes[0]


@pytest.mark.parametrize(
    "flag", sorted({"isActive", "tradingEnabled", "allowOvernight"})
)
def test_a_child_may_always_give_LESS_than_it_was_given(flag):
    # Tightening is the child's own business -- an admin closing a segment
    # the super admin left open must go through untouched.
    out, notes = clamp_child_patch({flag: False}, {flag: True})
    assert out[flag] is False
    assert notes == []


def test_a_permission_both_sides_agree_on_passes_quietly():
    for v in (True, False):
        out, notes = clamp_child_patch({"tradingEnabled": v}, {"tradingEnabled": v})
        assert out["tradingEnabled"] is v
        assert notes == []


@pytest.mark.parametrize("flag", ["blockInsideDayRange", "exitOnlyMode"])
def test_a_restriction_the_parent_set_cannot_be_lifted(flag):
    out, notes = clamp_child_patch({flag: False}, {flag: True})
    assert out[flag] is True
    assert notes and "super-admin" in notes[0]


@pytest.mark.parametrize("flag", ["blockInsideDayRange", "exitOnlyMode"])
def test_a_child_may_add_a_restriction_of_its_own(flag):
    out, notes = clamp_child_patch({flag: True}, {flag: False})
    assert out[flag] is True
    assert notes == []


def test_the_refusal_names_the_switch_not_the_field():
    _, notes = clamp_child_patch({"allowOvernight": True}, {"allowOvernight": False})
    assert "overnight carry" in notes[0]
    assert "allowOvernight" not in notes[0]


def test_modes_are_still_left_alone():
    # How margin is EXPRESSED is not a permission, and the margin-mode lock
    # is a separate, clearer check that rejects with its own message.
    out, notes = clamp_child_patch(
        {"marginCalcMode": "times", "commissionType": "flat"},
        {"marginCalcMode": "percent", "commissionType": "percent"},
    )
    assert out["marginCalcMode"] == "times"
    assert notes == []


def test_the_numbers_still_clamp_as_they_did():
    # The switch pass must not have swallowed the numeric one.
    out, notes = clamp_child_patch({"maxLotsPerOrder": 50}, {"maxLotsPerOrder": 10})
    assert out["maxLotsPerOrder"] == 10
    assert notes and "maximum allowed is 10" in notes[0]


def test_a_missing_parent_value_is_not_an_excuse_to_refuse():
    # A segment the parent has never touched has no opinion; blocking the
    # child there would be worse than the hole this closes.
    out, notes = clamp_child_patch({"tradingEnabled": True}, {})
    assert out["tradingEnabled"] is True
    assert notes == []
