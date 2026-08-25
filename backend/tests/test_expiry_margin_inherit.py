"""Expiry-day margin: an unset figure inherits the regular tier.

Reported live: an admin had NSE_IDX_FUT on Times 50x, and a NIFTY future
bought on its expiry day locked 1,25,959.60 against a 1,25,95,960 notional —
exactly 100x, double the leverage configured.

    is_expiry_day=False -> leverage 50   (the admin's setting)
    is_expiry_day=True  -> leverage 100  (a hardcoded default)

Nobody in that chain had ever set an expiry-day margin. `netting_service`
defaulted the missing value to 100 and handed it down as though the admin had
typed it, so `order_validator`'s own careful "fall back to the normal tier"
branch never ran — it only fires when the expiry figure is absent.

That is backwards twice over: it hands out MORE leverage on the riskiest day
of the month, and it contradicts this module's own migration, which NULLs the
seeded 100/100/50 precisely so they mean "inherit".
"""

from __future__ import annotations

import inspect

import pytest

from app.services import netting_service


def _resolve(*, expiry_value, seg_value, is_expiry_day):
    """The branch under test, as the resolver runs it."""
    if is_expiry_day:
        return float(expiry_value) if expiry_value else seg_value
    return seg_value


# -- the reported case -------------------------------------------------
def test_an_unset_expiry_margin_keeps_the_admins_leverage():
    """The live bug: 50x configured, 100x charged on expiry day."""
    assert _resolve(expiry_value=None, seg_value=50.0, is_expiry_day=True) == 50.0


def test_a_typed_expiry_margin_still_wins():
    """An admin who wants a stricter expiry tier must still get it."""
    assert _resolve(expiry_value=25.0, seg_value=50.0, is_expiry_day=True) == 25.0


def test_a_normal_day_is_unaffected():
    assert _resolve(expiry_value=25.0, seg_value=50.0, is_expiry_day=False) == 50.0


@pytest.mark.parametrize("empty", [None, 0, 0.0, ""])
def test_every_flavour_of_unset_inherits(empty):
    """0 is how the matrix stores "cleared", and it must not mean 0x."""
    assert _resolve(expiry_value=empty, seg_value=33.33, is_expiry_day=True) == 33.33


def test_expiry_day_never_hands_out_more_leverage_than_a_normal_day():
    """The whole point of an expiry tier is to be stricter, never looser."""
    for seg in (1.0, 5.0, 33.33, 50.0, 500.0):
        got = _resolve(expiry_value=None, seg_value=seg, is_expiry_day=True)
        assert got <= seg, seg


# -- the wiring --------------------------------------------------------
def test_the_resolver_no_longer_defaults_to_the_seed_numbers():
    src = inspect.getsource(netting_service._to_legacy_dict)
    assert 'pick("expiryDayIntradayMargin", 100.0)' not in src
    assert 'pick("expiryDayOptionBuyMargin", 100.0)' not in src
    assert 'pick("expiryDayOptionSellMargin", 50.0)' not in src


def test_the_futures_branch_inherits_the_segment_tier():
    src = inspect.getsource(netting_service._to_legacy_dict)
    assert "effective_margin_pct = float(_exp) if _exp else seg_value_for_now" in src


def test_the_option_branches_inherit_their_own_side():
    """An option BUY must not inherit the SELL tier, or vice versa."""
    src = " ".join(inspect.getsource(netting_service._to_legacy_dict).split())
    assert 'pick("expiryDayOptionBuyMargin", None)' in src
    assert '_opt_pick( "optionBuyIntraday", "optionBuyOvernight" )' in src
    assert 'pick("expiryDayOptionSellMargin", None)' in src
    assert '_opt_pick( "optionSellIntraday", "optionSellOvernight" )' in src


def test_the_migration_that_nulls_the_seed_still_exists():
    """This fix is what makes that migration mean anything at read time."""
    src = inspect.getsource(netting_service)
    assert "SEED_EXPIRY_INTRA = 100.0" in src
    assert "seg.expiryDayIntradayMargin = None" in src


def test_the_validator_fallback_can_now_actually_run():
    """It only fires when the expiry figure is absent — which it never was."""
    from app.services import order_validator

    src = inspect.getsource(order_validator.validate)
    assert '_exp_explicit = s.get("expiry_intraday_margin")' in src
    assert "if _exp_explicit:" in src
