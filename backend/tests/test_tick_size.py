"""MCX gold, silver, crude and copper FUTURES trade in whole rupees.

Operator: "GOLD, SILVER, CRUDE and COPPER only fixed 1 rs, position not in
paise — tick size 1 ka tick kar dena."

Two things had to change, because the tick was never actually doing anything:

  * `tick_size` has been stored on every Instrument from the start and
    `quantize_price` has existed the whole time, but NOTHING in the codebase
    ever called it. A limit or stop could rest at a price the contract does
    not trade at.

  * the values themselves came straight from the Zerodha dump, which is not
    even self-consistent: SILVER100 arrived at tick 1.0 for the SEP contract
    and 0.05 for DEC — same contract, different month.

An override rather than a database edit, because the catalog is rebuilt from
that dump every morning at 07:30; anything written into the rows would be gone
by the next session.

FUTURES ONLY, and confirmed as such: a COPPER option's premium is around 13.99,
so a 1-rupee tick there would be a ~7% step. Options keep the exchange's tick.
"""

from __future__ import annotations

import inspect

from app.services.instrument_service import tick_size_for
from app.utils.decimal_utils import quantize_price, to_decimal


# ── the four roots, and their families ────────────────────────────────
def test_the_named_futures_all_come_out_at_one_rupee():
    for sym, dflt in (
        ("GOLD26OCTFUT", 1.0),
        ("SILVER10026DECFUT", 0.05),
        ("SILVER10026SEPFUT", 1.0),
        ("COPPER26DECFUT", 0.05),
        ("CRUDEOIL26SEPFUT", 0.1),
    ):
        assert tick_size_for(sym, "FUT", dflt) == 1.0, sym


def test_the_family_variants_come_with_the_root():
    """GOLDM, SILVERM and SILVER100 are the same commodity in a smaller
    contract — normalising the root without them would leave the operator with
    exactly the inconsistency being fixed."""
    for sym in ("GOLDM26OCTFUT", "GOLDTEN26SEPFUT", "SILVERM26SEPFUT", "CRUDEOILM26SEPFUT"):
        assert tick_size_for(sym, "FUT", 0.05) == 1.0, sym


def test_an_already_correct_tick_is_left_where_it_is():
    assert tick_size_for("GOLD26OCTFUT", "FUT", 1.0) == 1.0


# ── everything else keeps the exchange's tick ─────────────────────────
def test_options_on_the_same_roots_are_untouched():
    """A COPPER option's premium is about 13.99. A 1-rupee tick would be a 7%
    step on it, so the options stay where the exchange put them."""
    assert tick_size_for("COPPER26NOV1210CE", "CE", 0.01) == 0.01
    assert tick_size_for("GOLD26DEC118000CE", "CE", 0.5) == 0.5
    assert tick_size_for("CRUDEOIL26OCT10000PE", "PE", 0.1) == 0.1


def test_other_futures_are_untouched():
    """Only the four the operator named. ZINC and ALUMINIUM are MCX too and
    keep 0.05; NSE futures are not in this at all."""
    assert tick_size_for("ZINC26SEPFUT", "FUT", 0.05) == 0.05
    assert tick_size_for("NIFTY26SEPFUT", "FUT", 0.05) == 0.05
    assert tick_size_for("ALUMINIUM26SEPFUT", "FUT", 0.05) == 0.05


def test_equities_are_untouched():
    assert tick_size_for("RELIANCE", "EQ", 0.05) == 0.05
    assert tick_size_for("GOLDBEES", "EQ", 0.01) == 0.01


def test_it_survives_the_junk_it_will_be_handed():
    """Called on every mirrored row, including half-formed ones."""
    assert tick_size_for(None, "FUT", 0.05) == 0.05
    assert tick_size_for("", None, 0.05) == 0.05
    assert tick_size_for("GOLD26OCTFUT", None, 0.05) == 0.05


def test_an_enum_instrument_type_works_as_well_as_a_string():
    """The mirror passes a raw string, the API path passes the enum."""
    from app.models._base import InstrumentType

    assert tick_size_for("GOLD26OCTFUT", InstrumentType.FUT, 0.05) == 1.0
    assert tick_size_for("GOLD26DEC118000CE", InstrumentType.CE, 0.5) == 0.5


# ── it is an override, not a data edit ────────────────────────────────
def test_the_reason_it_is_code_and_not_a_migration_is_recorded():
    src = inspect.getsource(tick_size_for)
    assert "07:30" in src or "rebuilt" in src


def test_every_path_that_writes_a_tick_goes_through_it():
    """Three of them: the catalog mirror, the search row, and the on-demand
    mirror. One left out would put the old value back."""
    from app.api.v1.user import instruments as api
    from app.services import instrument_service as isvc

    assert "tick_size_for(sym, it_str" in inspect.getsource(isvc)
    api_src = inspect.getsource(api)
    assert api_src.count("instrument_service.tick_size_for(") == 2


# ── the tick is now actually applied ──────────────────────────────────
def test_a_typed_price_snaps_to_the_tick():
    for raw, tick, want in (
        ("8650.37", "1", "8650"),
        ("8650.60", "1", "8651"),
        ("155052.49", "1", "155052"),
        ("1400.03", "0.05", "1400.05"),
    ):
        got = quantize_price(to_decimal(raw), tick_size=to_decimal(tick))
        assert got == to_decimal(want), (raw, tick, got)


def test_the_order_path_snaps_both_the_limit_and_the_trigger():
    from app.services import order_service

    src = inspect.getsource(order_service.place_order)
    assert "price = quantize_price(price, tick_size=_tick)" in src
    assert "trigger = quantize_price(trigger, tick_size=_tick)" in src


def test_a_market_order_is_unaffected():
    """It carries no price, and 0 is skipped."""
    from app.services import order_service

    src = inspect.getsource(order_service.place_order)
    assert "if price > 0:" in src
    assert "if trigger > 0:" in src


def test_the_fill_price_is_deliberately_left_alone():
    """Rounding a fill would move realised P&L away from the market by up to
    half a tick on every single trade. Only what the user TYPED is snapped."""
    from app.services import order_service

    src = inspect.getsource(order_service.place_order)
    assert "quantize_price(force_fill_price" not in src
    assert "quantize_price(expected_price" not in src


def test_a_missing_tick_is_a_no_op_rather_than_a_guess():
    """An instrument with tick 0 or none must not be snapped to whole rupees
    by accident."""
    from app.services import order_service

    assert "if _tick > 0:" in inspect.getsource(order_service.place_order)
