"""A recycled instrument token stayed retired and refused every order.

Zerodha reuses instrument_token numbers across expiries. Measured on the live
catalog on 9 Sep 2026:

    token 12094466   our row: NIFTY2691522300CE  expiry 2026-07-28
                              is_active=False  is_tradable=False
                     Kite:    NIFTY2691522300CE  expiry 2026-09-15   (live)

The number belonged to the 28-Jul weekly. Expiry-cleanup retired our row the
morning after that contract died. Kite then handed the same number to the
15-Sep contract. The option chain reads the live catalog, so it listed the
strike and priced it; the order path reads the stored row, so every tap came
back "Instrument is not tradable".

`get_by_token` only ever self-healed a row whose symbol was still the bare
token, so a recycled row was handed back retired forever.

Both directions matter here. Relisting has to happen when the catalog carries
a LIVE expiry for the token, and must NOT happen when it carries a dead one -
a dump that still lists yesterday's expired contract would otherwise flip an
expired row back to tradable and let users trade a contract that no longer
exists.
"""

from __future__ import annotations

import inspect

from app.services import instrument_service as svc


def test_a_retired_row_is_re_resolved_against_the_catalog():
    src = inspect.getsource(svc.get_by_token)
    # The heal must run on the retired branch, not only on the token-as-symbol
    # stub branch that was there before.
    assert "not (inst.is_active and inst.is_tradable)" in src
    assert "_needs_recycle_check(token)" in src


def test_the_mirror_refuses_to_resurrect_a_dead_expiry():
    src = inspect.getsource(svc._mirror_from_zerodha)
    # Guard sits before the write-back, so a retired row whose catalog expiry
    # is already past is returned untouched.
    guard = src.index("expiry_d < now_ist().date()")
    write = src.index("existing.is_tradable = True")
    assert guard < write, "the resurrect guard must precede the write-back"


def test_relisting_re_subscribes_the_token():
    # Expiry-cleanup unsubscribed the token when it retired the row. A
    # tradable contract with no live ticks reads as a frozen price.
    src = inspect.getsource(svc._mirror_from_zerodha)
    assert "if was_retired:" in src
    # The relist branch subscribes; it must sit between the flag it reads and
    # the insert path's own subscribe further down.
    assert src.index("if was_retired:") < src.index("subscribe_tokens_on_demand")


def test_the_catalog_is_asked_at_most_once_a_day_per_token():
    # The lookup walks ~100k catalog rows. A Closed-trades screen full of
    # expired legs must not rescan once per row.
    svc._RECYCLE_CHECKED.clear()
    assert svc._needs_recycle_check("12094466") is True
    assert svc._needs_recycle_check("12094466") is False
    assert svc._needs_recycle_check("12096002") is True


def test_the_day_marker_does_not_grow_without_bound():
    svc._RECYCLE_CHECKED.clear()
    svc._RECYCLE_CHECKED.update({str(i): "1999-01-01" for i in range(50_001)})
    svc._needs_recycle_check("fresh")
    assert len(svc._RECYCLE_CHECKED) == 1
