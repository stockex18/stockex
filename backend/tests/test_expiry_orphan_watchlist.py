"""Expired crypto options stayed on watchlists, each showing 0.00.

Measured live: 8 watchlist rows pointing at BTC options that expired 14-16 Aug,
a month earlier. The instruments themselves were correctly retired
(is_active=False) — only their watchlist rows survived.

Two things retire a contract, and only one of them cleaned watchlists:

    expiry_cleanup          picks up `is_active: True` expired rows, deletes
                            their watchlist items, then marks them inactive
    binance_options_service flips a crypto option inactive the moment it leaves
                            the universe, and never touches watchlists

The second one always ran first, so by the time the cleanup looked, the row
was already inactive and never a candidate. Its watchlist items were orphaned
for good.

The orphan sweep covers every retirement path from one place rather than
teaching each retirer to clean up after itself.
"""

from __future__ import annotations

import inspect

from app.services import expiry_cleanup as ec

SRC = inspect.getsource(ec.cleanup_expired_once)


def test_orphans_are_swept_on_expired_and_inactive():
    assert '{"expiry": {"$ne": None, "$lt": today}, "is_active": False}' in SRC
    assert "WatchlistItem.find(" in SRC


def test_an_instrument_switched_off_for_another_reason_keeps_its_row():
    # Keyed on EXPIRED + inactive, not inactive alone — an admin block or a
    # halted script may come back, and the user should get their row back too.
    i = SRC.index("orphans_removed = 0")
    block = SRC[i : SRC.index("# Past-expiry contracts")]
    assert '"$lt": today' in block
    assert '"is_active": False' in block


def test_the_sweep_runs_before_the_early_return():
    # The measured orphans had NO fresh candidate beside them, so a sweep
    # placed after "nothing to do, return" would never have reached them.
    assert SRC.index("orphans_removed = 0") < SRC.index("if not to_settle and not to_retire:")


def test_both_returns_report_the_orphans():
    assert '"watchlist_items": orphans_removed,' in SRC
    assert '"watchlist_items": wl_removed + orphans_removed,' in SRC


def test_a_failed_sweep_never_blocks_settlement():
    i = SRC.index("orphans_removed = 0")
    block = SRC[i : SRC.index("# Past-expiry contracts")]
    assert "except Exception" in block
    assert "expiry_cleanup_orphan_sweep_failed" in block


def test_the_binance_retirer_is_the_path_that_needed_it():
    # If this ever starts cleaning watchlists itself the sweep is merely
    # redundant; if it stops retiring, the sweep is still harmless.
    from app.services import binance_options_service as bos

    src = inspect.getsource(bos)
    assert '{"$set": {"is_active": False, "is_tradable": False}}' in src
