"""The carry sweep must run once a day, restart or no restart.

Seen live on 2026-09-07. The NSE rollover fired correctly at 15:41 and trimmed
the book. A backend restart landed at ~15:45. At 15:58 the sweep ran AGAIN and
took a second slice out of the same positions:

    15:41:04  BANKNIFTY26SEPFUT  SELL 130.53   CARRY_FORWARD_TRIM
    15:41:05  NIFTY26SEPFUT      BUY  250.95   (313.95 -> 63)
    ...
    15:58:47  NIFTY26SEPFUT      BUY    6.00   <- second run
    15:58:48  NIFTY26SEPFUT      SELL 105.00
    15:58:49  BANKNIFTY26SEPFUT  BUY   33.53

`_last_rollover_day` was a plain module-level dict, so every restart wiped the
"already done" marker and any deploy after the close re-ran the whole sweep.
"""

from __future__ import annotations

import inspect

import pytest

import app.core.redis_client as rc
from app.services import position_service as ps


class _FakeRedis:
    def __init__(self):
        self.d = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, ex=None):
        self.d[k] = v


@pytest.fixture
def redis(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(rc, "get_redis", lambda: r)
    ps._last_rollover_day.clear()
    yield r
    ps._last_rollover_day.clear()


async def test_it_has_not_run_before_it_runs(redis):
    assert await ps._rollover_already_done("NSE", "20260907") is False


async def test_it_knows_it_has_run(redis):
    await ps._mark_rollover_done("NSE", "20260907")
    assert await ps._rollover_already_done("NSE", "20260907") is True


async def test_a_restart_does_not_make_it_run_again(redis):
    """The whole point. Clearing the in-process dict is exactly what a restart
    does; Redis still remembers."""
    await ps._mark_rollover_done("NSE", "20260907")
    ps._last_rollover_day.clear()
    assert await ps._rollover_already_done("NSE", "20260907") is True


async def test_tomorrow_it_runs_again(redis):
    await ps._mark_rollover_done("NSE", "20260907")
    assert await ps._rollover_already_done("NSE", "20260908") is False


async def test_each_group_is_tracked_separately(redis):
    """NSE closes at 15:30 and MCX at 23:30 — one must not mark the other."""
    await ps._mark_rollover_done("NSE", "20260907")
    assert await ps._rollover_already_done("MCX", "20260907") is False
    assert await ps._rollover_already_done("CRYPTO", "20260907") is False


async def test_a_redis_failure_fails_closed(monkeypatch):
    """Running the sweep twice squares off real positions; skipping it once
    only leaves them on intraday margin until the next run. The second is the
    one you can recover from, so an unreadable marker means 'already done'."""

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rc, "get_redis", boom)
    ps._last_rollover_day.clear()
    assert await ps._rollover_already_done("NSE", "20260907") is True


def test_the_marker_is_written_before_the_sweep_not_after():
    """The sweep places real orders and can take a while. A restart in the
    middle of it would otherwise re-run the whole thing from the top."""
    src = inspect.getsource(ps.intraday_to_carry_loop)
    i = src.index('_mark_rollover_done(group_name, day_key)')
    j = src.index("convert_intraday_to_carry(group_set)")
    assert i < j


def test_both_paths_use_the_guard():
    src = inspect.getsource(ps.intraday_to_carry_loop)
    assert "await _rollover_already_done(group_name, day_key)" in src
    assert 'await _rollover_already_done("CRYPTO", _ck)' in src
    # the bare dict comparison is gone from the loop
    assert "_last_rollover_day.get(group_name) == day_key" not in src
    assert '_last_rollover_day.get("CRYPTO") != _ck' not in src


# ── the flip that ran out of free cash mid-sweep ──────────────────────
def test_a_failed_conversion_is_retried_after_the_sweep():
    """Live, 2026-09-07 MCX: converted=12 force_closed=8 skipped=2, and both
    skipped legs were the same failure -

        CRUDEOIL26SEP8800PE  have 1,75,416.15  need 1,84,823.60
        CRUDEOIL26SEPFUT     have    33,064.99  need    61,567.00

    an InsufficientFundsError inside `block_margin` on the MIS->NRML flip. Both
    were left in MIS overnight.

    Not a real shortage - an ORDERING one. The sweep walks positions one at a
    time, and the legs that RELEASE margin can come after the one that needs to
    BLOCK more, so free cash is momentarily short even though the portfolio as a
    whole fits. The planner has already checked that it does.
    """
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert "_deferred.append((pos, new_margin, delta))" in src
    assert "for pos, new_margin, delta in _deferred:" in src


def test_the_retry_happens_after_every_square_and_release():
    """That is the whole point - it has to run once the margin is back."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert src.index("_deferred.append(") < src.index("for pos, new_margin, delta in _deferred:")


def test_the_retry_rechecks_the_position_before_touching_it():
    """It may have been squared, closed or already flipped by the time the
    second pass reaches it."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    i = src.index("for pos, new_margin, delta in _deferred:")
    block = src[i : i + 900]
    assert "refreshed = await Position.get(pos.id)" in block
    assert "refreshed.status != PositionStatus.OPEN" in block
    assert "refreshed.product_type != _PT.MIS" in block


def test_it_retries_once_and_does_not_force_close_on_a_second_failure():
    """If the money genuinely is not there, the next sweep deals with it - it
    looks at MIS rows too. Force-closing here would be a second guess against
    a plan that said the position could carry."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    i = src.index("for pos, new_margin, delta in _deferred:")
    block = src[i : i + 1600]
    assert "carry_convert_retry_failed" in block
    assert "place_order" not in block
    assert "skipped += 1" in block


def test_both_outcomes_are_logged():
    src = inspect.getsource(ps.convert_intraday_to_carry)
    assert "carry_convert_retry_ok" in src
    assert "carry_convert_retry_failed" in src


def test_a_successful_retry_counts_as_converted():
    """The summary line is how the operator sees whether a sweep went cleanly;
    a retry that worked is a conversion, not a skip."""
    src = inspect.getsource(ps.convert_intraday_to_carry)
    i = src.index("carry_convert_retry_ok")
    assert "converted += 1" in src[i - 400 : i]
