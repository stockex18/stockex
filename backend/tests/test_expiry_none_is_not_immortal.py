"""A derivative with no expiry date must not live for ever.

The daily sweep only ever looks at `{"expiry": {"$ne": None}}`. A future or
option whose expiry is null is therefore invisible to it: permanently
tradable, permanently on watchlists, permanently quoting whatever it last
held.

Found live on 23 Sept — CRUDEOIL26SEPFUT, expiry null, still tradable four
days after the September contract died. Zerodha's own catalogue started at
26OCT, and our mirror held ltp = bid = ask = 9158.00 on zero volume, which is
what a dead contract looks like. A user could have opened a position on it.
"""

from __future__ import annotations

import inspect

from app.services import expiry_cleanup as ec


def _src() -> str:
    return inspect.getsource(ec._heal_missing_expiry)


def test_the_sweep_really_does_skip_a_null_expiry():
    """The reason this healer has to exist."""
    s = inspect.getsource(ec.cleanup_expired_once)
    assert '{"expiry": {"$ne": None, "$lte": today}, "is_active": True}' in s


def test_the_heal_runs_before_the_sweep_that_cannot_see_them():
    s = inspect.getsource(ec.cleanup_expired_once)
    assert "_heal_missing_expiry()" in s
    assert s.index("_heal_missing_expiry()") < s.index('"$lte": today')


def test_it_only_looks_at_derivatives():
    """An equity has no expiry and never should — healing one would be a bug."""
    s = _src()
    assert '"segment": {"$regex": "FUT|OPT", "$options": "i"}' in s
    assert '"expiry": None' in s and '"is_active": True' in s


def test_a_contract_the_exchange_dropped_is_retired():
    s = _src()
    assert "if row is None:" in s
    assert "inst.is_active = False" in s
    assert "inst.is_tradable = False" in s


def test_a_contract_still_listed_just_gets_its_date_back():
    s = _src()
    assert "exp = row.get(\"expiry\")" in s
    assert "inst.expiry = (" in s


def test_the_catalogue_is_read_once_per_exchange():
    """One fetch per instrument would be thousands of calls on an option
    chain."""
    s = _src()
    assert "for exch in {" in s
    assert s.index("for exch in {") < s.index("for inst in rows:")


def test_no_catalogue_means_no_decision():
    """Retiring a contract because the catalogue call failed would delist a
    live instrument."""
    s = _src()
    assert "expiry_heal_catalogue_unavailable" in s
    assert "return 0" in s.split("expiry_heal_catalogue_unavailable")[1][:200]


def test_it_never_blocks_the_sweep():
    s = inspect.getsource(ec.cleanup_expired_once)
    assert "expiry_heal_failed_continuing" in s


def test_every_change_is_logged_loudly_enough_to_find():
    s = _src()
    for probe in ("expiry_heal_retired_delisted", "expiry_heal_filled", "expiry_heal_done"):
        assert probe in s, probe
