"""One lot of GOLDTEN is one contract, not a hundred.

Operator: "gold ten me ek lot me 1 qty hi hoti hai, 100 galat hai."

MCX quotes gold in rupees per 10 grams, and GOLDTEN *is* a 10 gram contract —
so one lot is exactly the quoted price. It had no row of its own and matched
the GOLD prefix, which made every GOLDTEN order a hundred times its size: a
lot priced at 1,51,600 was charged 1,51,60,000 of notional.

Looking for it turned up the same trap twice more, one of which was already
live: ALUMINIUM (5 MT) sat BELOW ALUMINI (1 MT) in a table that asks to be
kept longest-first, so the big contract was being priced as the mini.
"""

from __future__ import annotations

import inspect

from app.services import index_lots
from app.services.index_lots import MCX_LOT_SIZES, get_mcx_lot_size


def test_goldten_is_one_lot_one_contract():
    assert get_mcx_lot_size("GOLDTEN26SEPFUT") == 1
    assert get_mcx_lot_size("GOLDTEN26OCTFUT") == 1


def test_the_rest_of_the_gold_family_is_unchanged():
    """Each is (contract size ÷ the 10 gram quote unit)."""
    assert get_mcx_lot_size("GOLD26OCTFUT") == 100          # 1 kg
    assert get_mcx_lot_size("GOLDM26OCTFUT") == 10          # 100 g
    assert get_mcx_lot_size("GOLDGUINEA26SEPFUT") == 1      # 8 g
    assert get_mcx_lot_size("GOLDPETAL26SEPFUT") == 1       # 1 g


def test_the_big_aluminium_contract_is_not_priced_as_the_mini():
    assert get_mcx_lot_size("ALUMINIUM26SEPFUT") == 5000
    assert get_mcx_lot_size("ALUMINI26SEPFUT") == 1000


def test_a_contract_matches_its_own_root_not_somebody_elses_prefix():
    """The whole class of bug: `startswith` let an unlisted commodity inherit
    the multiplier of whichever listed one it happened to begin with."""
    s = inspect.getsource(index_lots._match_prefix)
    assert "if root in exact:" in s
    # The docstring still explains the old behaviour, so check the CODE.
    body = s.split('"""')[-1]
    assert "startswith" not in body


def test_the_answer_does_not_depend_on_the_table_order():
    reversed_table = list(reversed(MCX_LOT_SIZES))
    assert index_lots._match_prefix(reversed_table, "ALUMINIUM26SEPFUT") == 5000
    assert index_lots._match_prefix(reversed_table, "GOLDTEN26SEPFUT") == 1
    assert index_lots._match_prefix(reversed_table, "SILVERMIC26NOVFUT") == 1


def test_cottonseed_oilcake_is_not_cotton():
    """Different commodity, different contract — it only shares five letters."""
    assert get_mcx_lot_size("COTTON26SEPFUT") == 25
    assert get_mcx_lot_size("COTTONOIL26SEPFUT") == 100


def test_an_unlisted_commodity_borrows_nobody_elses_number():
    """It must resolve to None so the caller keeps the feed's own lot size,
    rather than silently taking a multiplier that was never about it."""
    assert get_mcx_lot_size("STEELREBAR26SEPFUT") is None
    assert get_mcx_lot_size("MCXBULLDEX26SEPFUT") is None


def test_index_options_still_find_their_root_past_the_strike():
    """Options carry a strike after the expiry, so the root is the letters
    before the first digit."""
    from app.services.index_lots import get_index_lot_size

    assert get_index_lot_size("NIFTY26SEP23500CE") == get_index_lot_size("NIFTY")
    assert get_index_lot_size("BANKNIFTY26SEP56800PE") == get_index_lot_size("BANKNIFTY")
    # A stock option matches no index row and falls back to the feed, as before.
    assert get_index_lot_size("RELIANCE26SEP1400CE") is None


def test_every_family_still_separates_from_its_own_mini():
    pairs = [
        ("SILVER26DECFUT", 30), ("SILVERM26NOVFUT", 5), ("SILVERMIC26NOVFUT", 1),
        ("CRUDEOIL26OCTFUT", 100), ("CRUDEOILM26OCTFUT", 10),
        ("ZINC26SEPFUT", 5000), ("ZINCMINI26SEPFUT", 1000),
        ("LEAD26SEPFUT", 5000), ("LEADMINI26SEPFUT", 1000),
    ]
    for sym, want in pairs:
        assert get_mcx_lot_size(sym) == want, sym


def test_an_unknown_commodity_keeps_whatever_the_feed_says():
    assert get_mcx_lot_size("MCXBULLDEX26SEPFUT") is None
    assert get_mcx_lot_size("STEELREBAR26SEPFUT") is None
