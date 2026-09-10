"""EXIT and Square off all still closed a position locked at its circuit.

Reported on HEG-BE. Measured on the live box while the position was open:

    band   lc 249.65   uc 275.85
    ltp    249.65                 -> sitting ON the lower circuit

Every automatic close already refused it (`risk_enforcer._at_circuit` holds
SL, TP, margin call and stop-out) and `order_validator` refuses a reducing
order — yet both user buttons went through.

The reason is that both user endpoints send `is_squareoff=True`, and that is
exactly the flag the validator's circuit gate skips on. The flag was meant to
mean "admin force-close or the risk enforcer", but `positions.py` sets it for
an ordinary user tap as well, so it could never carry that meaning.

Hence the gate belongs in the user-only endpoints, where the intent is not in
doubt. It shares `_at_circuit` with the enforcer rather than re-deriving the
band, so the two cannot end up disagreeing about what "locked" means.

Square off all SKIPS a locked row and counts it, rather than failing the whole
batch — one locked stock must not stop the user flattening everything else.
"""

from __future__ import annotations

import inspect

from app.api.v1.user import positions as pos
from app.services import risk_enforcer as re


SRC = inspect.getsource(pos)


def test_the_single_close_refuses_a_locked_circuit():
    assert "_circuit_locked(p.instrument)" in SRC
    assert "locked at its circuit" in SRC


def test_square_off_all_skips_a_locked_row_and_counts_it():
    assert "blocked_by_circuit += 1" in SRC
    assert '"blocked_by_circuit": blocked_by_circuit' in SRC


def test_one_locked_row_does_not_fail_the_whole_batch():
    # `continue`, not `raise` — the other positions still flatten.
    i = SRC.index("blocked_by_circuit += 1")
    assert "continue" in SRC[i : i + 60]


def test_both_paths_share_the_enforcer_s_definition_of_locked():
    # Re-deriving the band here is how the user side ends up disagreeing with
    # the automatic side about the same stock.
    assert SRC.count("from app.services.risk_enforcer import _at_circuit as _circuit_locked") == 2
    assert "_circuit_limits" not in SRC


def test_the_gate_is_not_left_to_the_squareoff_flag():
    # `is_squareoff=True` is what the user endpoints send, so the validator's
    # gate can never fire for them — the check has to be here.
    assert '"is_squareoff": True' in SRC


def test_a_missing_band_still_lets_the_user_out():
    # Fail-open: a circuit lookup problem must never trap someone in a trade.
    src = inspect.getsource(re._at_circuit)
    assert "if lc is None and uc is None:\n            return False" in src
    assert "except Exception:" in src


def test_a_price_sitting_exactly_on_the_band_counts_as_locked():
    # HEG-BE was AT 249.65 with lc 249.65 — `>` would have missed it.
    src = inspect.getsource(re._at_circuit)
    assert "px >= uc" in src and "px <= lc" in src
