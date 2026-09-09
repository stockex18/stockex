"""User Square Off was the one close still going through a locked circuit.

Operator's rule set, in full:

    upper circuit  -> SELL allowed, BUY restricted
                      an existing BUY position must not Square Off
                      after selling 1 lot, a later BUY must not execute
    lower circuit  -> BUY allowed, SELL restricted
                      an existing SELL position must not Square Off
                      after buying 1 lot, a later SELL must not execute

Read together those say two different things, and the difference is what was
missing. NEW positions are direction-gated - at the ceiling nobody is selling
to you, at the floor nobody is buying from you. CLOSING is blocked outright,
either circuit, either side: the "buy position + upper circuit" and "sell
position + lower circuit" cases are the ones on the ALLOWED side of the
direction rule, so only a blanket block covers them.

Every AUTOMATIC close already worked this way - `risk_enforcer._at_circuit`
holds SL, TP, margin call and stop-out against a locked band. User-initiated
Square Off / Square Off All went through `order_validator`, which exempted
`is_reducing` from the circuit gate entirely, so the one close a human asks
for was the one close that fired into a market nobody can trade in.

Kept out of it deliberately:
  - `is_squareoff` (admin force-close, risk enforcer) still bypasses; the
    enforcer holds itself back a layer earlier and an admin override must
    stay an override.
  - crypto has no exchange band and the operator chose not to invent one, so
    `_CIRCUIT_EXCHANGES` is unchanged and crypto never reaches this gate.
"""

from __future__ import annotations

import inspect

from app.services import order_validator as ov


SRC = inspect.getsource(ov.validate_order) if hasattr(ov, "validate_order") else ""


def _gate_src() -> str:
    """The circuit block, from its banner to the notional line after it."""
    src = inspect.getsource(ov)
    i = src.index("# ── Circuit gate")
    return src[i : src.index("notional = to_decimal(quantity)", i)]


def test_closing_is_blocked_at_either_circuit():
    g = _gate_src()
    assert "if is_reducing:" in g
    assert "if at_upper or at_lower:" in g
    assert "CIRCUIT_LOCKED_NO_EXIT" in g


def test_the_block_is_not_direction_dependent():
    # A long closes with a SELL, which the direction rule ALLOWS at the upper
    # circuit. Only a side-independent check stops it, so the reducing branch
    # must not look at `action`.
    g = _gate_src()
    branch = g[g.index("if is_reducing:") : g.index("else:")]
    assert "OrderAction" not in branch


def test_new_positions_keep_the_direction_rule():
    g = _gate_src()
    assert "at_upper and action == OrderAction.BUY" in g
    assert "at_lower and action == OrderAction.SELL" in g
    assert "UPPER_CIRCUIT_BUY" in g and "LOWER_CIRCUIT_SELL" in g


def test_admin_force_close_and_the_risk_enforcer_still_bypass():
    g = _gate_src()
    assert "if not is_squareoff:" in g
    # The whole gate hangs off that one branch — nothing below re-tests it, so
    # an admin/enforcer close skips every circuit rule at once.
    body = g[g.index("if not is_squareoff:") :]
    assert body.count("is_squareoff") == 1


def test_a_missing_band_never_blocks_anything():
    # `_circuit_limits` fails open to (None, None); both flags then read False.
    g = _gate_src()
    assert "at_upper = uc is not None" in g
    assert "at_lower = lc is not None" in g
    src = inspect.getsource(ov._circuit_limits)
    assert "return (None, None)" in src


def test_crypto_is_not_in_the_circuit_scope():
    # No exchange publishes a crypto band and the operator chose not to invent
    # one; `_circuit_limits` returns no opinion for anything off this list.
    assert "CRYPTO" not in ov._CIRCUIT_EXCHANGES
    assert ov._CIRCUIT_EXCHANGES == ("NSE", "BSE", "NFO", "BFO", "MCX", "CDS")


def test_the_price_band_check_stays_on_opens_only():
    # A LIMIT priced outside the band is an OPENING concern; the reducing
    # branch raises before it and must not fall through into it.
    g = _gate_src()
    assert g.index("CIRCUIT_LOCKED_NO_EXIT") < g.index("UPPER_CIRCUIT\"")
