"""Every reason the carry sweep skips a position has to be on the record.

Last night's MCX run reported `skipped=2` and left two legs sitting in MIS
overnight — money locked in a position that neither carried nor squared — and
the logs could not say which branch did it or why. Six paths increment
`skipped`; only two of them said anything.

A skip nobody can explain is a skip nobody can fix, so this pins that none of
them can go quiet again.
"""

from __future__ import annotations

import inspect
import re

from app.services import position_service

SRC = inspect.getsource(position_service.convert_intraday_to_carry)
_WARN = re.compile(r'_clog\.warning\(\s*"([^"]+)"')


def _skip_messages() -> list[str]:
    """Only the warnings that belong to a skip path.

    The wallet-reconcile warning in this same function is per-USER by nature
    and is not one of them, so scanning every warning would be the wrong test.
    """
    lines = SRC.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if "skipped += 1" not in line:
            continue
        out += _WARN.findall("\n".join(lines[max(0, i - 8):i]))
    return out


def test_every_skip_path_says_why():
    """Walk back from each `skipped += 1` and require a log close enough to
    belong to it."""
    lines = SRC.splitlines()
    silent = []
    for i, line in enumerate(lines):
        if "skipped += 1" not in line:
            continue
        if "_clog.warning" not in "\n".join(lines[max(0, i - 8):i]):
            silent.append((i, line.strip()))
    assert not silent, "skip paths with no log: " + str(silent)


def test_the_sweep_still_has_the_paths_we_think_it_does():
    """If a branch is added later this count changes, and the test above only
    passes once the new one is logged too."""
    assert SRC.count("skipped += 1") == 7


def test_each_message_names_the_position():
    """A count in a summary line is not a diagnosis — the row has to be
    identifiable."""
    msgs = _skip_messages()
    assert msgs, "no skip-path warnings found at all"
    for m in msgs:
        assert "pos=%s" in m, m


def test_the_branches_are_distinguishable():
    """Two paths share `carry_user_missing`, so they carry a branch tag."""
    msgs = _skip_messages()
    shared = [m for m in msgs if "carry_user_missing" in m]
    assert len(shared) == 2
    assert all("branch=" in m for m in shared)


def test_the_convert_failure_is_named():
    """An affordable position that fails to flip is exactly what strands a leg
    in MIS overnight — the case reported."""
    assert "carry_convert_failed" in SRC


def test_settings_failures_are_named():
    assert "carry_settings_resolve_failed" in SRC


def test_logging_never_swallows_the_traceback():
    """Without it the message names the row but not the cause."""
    assert SRC.count("exc_info=True") >= 4
