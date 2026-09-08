"""Every reason the backend can stamp has to read as something on the screen.

Operator: "expiry se kitne baje trade close hui hai, aur reason me likh ke
dikha ki expiry ke karan hui hai, taki user ko dikhe konsi trade expiry se
close hui."

The chip map had eight entries and the backend emits more than that, so an
unmapped reason fell through and printed the raw enum - the screenshot shows
"CARRY_FORWARD_TRIM" sitting in a plain box - while an expiry showed nothing
recognisable at all.
"""

from __future__ import annotations

import io
import re
import subprocess

PAGE = r"D:\stockex_new\frontend-user\app\(dashboard)\positions\page.tsx"


def mapped() -> set[str]:
    s = io.open(PAGE, encoding="utf-8", errors="ignore").read()
    i = s.index("const CLOSE_REASON_META")
    block = s[i : s.index("\n};", i)]
    return set(re.findall(r"^  ([A-Z_]{3,}):", block, re.M))


def emitted() -> set[str]:
    """Whatever the backend actually writes into `close_reason`."""
    out = subprocess.run(
        ["git", "grep", "-hoE", r'close_reason[ =:]+"[A-Z_]{3,}"', "--", "app/"],
        cwd=r"D:\stockex_new\backend", capture_output=True, text=True,
    ).stdout
    found = set(re.findall(r'"([A-Z_]{3,})"', out))
    # `settle_expired_position(reason=...)` defaults, passed rather than assigned
    found |= {"EXPIRY_SETTLED", "CRYPTO_OPT_EXPIRY"}
    return found


def test_every_backend_reason_has_a_label():
    missing = emitted() - mapped()
    assert not missing, f"unmapped close reasons render as the raw enum: {sorted(missing)}"


def test_expiry_reads_as_expiry():
    s = io.open(PAGE, encoding="utf-8", errors="ignore").read()
    i = s.index("EXPIRY_SETTLED: {")
    assert 'label: "Expiry"' in s[i : i + 200]


def test_a_crypto_option_expiry_reads_the_same():
    """Different code path, same thing as far as the trader is concerned."""
    s = io.open(PAGE, encoding="utf-8", errors="ignore").read()
    i = s.index("CRYPTO_OPT_EXPIRY: {")
    assert 'label: "Expiry"' in s[i : i + 200]


def test_the_two_carry_outcomes_are_told_apart():
    """A planned portfolio trim is not the same event as "could not afford even
    the minimum step", and the chip should not blur them."""
    s = io.open(PAGE, encoding="utf-8", errors="ignore").read()
    assert 'CARRY_FORWARD_TRIM: {' in s
    assert 'CARRY_FORWARD_FAIL: {' in s
    i, j = s.index("CARRY_FORWARD_TRIM: {"), s.index("CARRY_FORWARD_FAIL: {")
    assert s[i : i + 200].split('label: "')[1] != s[j : j + 200].split('label: "')[1]


def test_the_reason_reaches_the_row_at_all():
    """It lives on the Position; the blotter is built from Trades. The enrich
    step matches them by token + product within 30 s of the close."""
    import inspect

    from app.services import position_service as ps

    src = inspect.getsource(ps.list_closed_trade_events_fifo)
    assert 'ev["close_reason"] = _best[1]' in src
    assert "total_seconds()) < 30" in src
