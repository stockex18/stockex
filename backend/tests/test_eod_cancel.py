"""Midnight sweep — no resting order outlives the day it was placed in.

Orders were sitting in Pending across days (placed 20 Aug, still OPEN on
21 Aug), so a price chosen against yesterday's market could still fire against
today's.
"""

from __future__ import annotations

import inspect

import pytest

from app.models.order import OrderStatus
from app.services import matching_engine as me


class _FakeOrder:
    def __init__(self, oid, status):
        self.id = oid
        self.status = status


def _wire(monkeypatch, rows, *, boom_on=()):
    cancelled = []

    class _Cur:
        def __init__(self, r):
            self._r = r

        async def to_list(self):
            return self._r

    captured = {}

    def _find(q):
        captured["query"] = q
        return _Cur(rows)

    async def _cancel(o, reason=None):
        if o.id in boom_on:
            raise RuntimeError("boom")
        cancelled.append((o.id, reason))
        return o

    monkeypatch.setattr(me.Order, "find", staticmethod(_find))
    monkeypatch.setattr(me, "cancel_order", _cancel)
    return cancelled, captured


async def test_cancels_every_resting_order(monkeypatch):
    rows = [_FakeOrder(1, OrderStatus.OPEN), _FakeOrder(2, OrderStatus.PENDING)]
    cancelled, _ = _wire(monkeypatch, rows)
    out = await me.cancel_all_resting_orders()
    assert out == {"cancelled": 2, "failed": 0}
    assert [c[0] for c in cancelled] == [1, 2]


async def test_query_targets_only_resting_states(monkeypatch):
    """EXECUTED / CANCELLED / REJECTED must never be touched."""
    _, captured = _wire(monkeypatch, [])
    await me.cancel_all_resting_orders()
    states = set(captured["query"]["status"]["$in"])
    assert states == {
        OrderStatus.OPEN.value,
        OrderStatus.PENDING.value,
        OrderStatus.PARTIAL.value,
    }
    assert OrderStatus.EXECUTED.value not in states


async def test_one_bad_order_does_not_stop_the_sweep(monkeypatch):
    rows = [_FakeOrder(1, OrderStatus.OPEN), _FakeOrder(2, OrderStatus.OPEN), _FakeOrder(3, OrderStatus.OPEN)]
    cancelled, _ = _wire(monkeypatch, rows, boom_on=(2,))
    out = await me.cancel_all_resting_orders()
    assert out == {"cancelled": 2, "failed": 1}
    assert [c[0] for c in cancelled] == [1, 3]


async def test_reason_is_stamped(monkeypatch):
    cancelled, _ = _wire(monkeypatch, [_FakeOrder(1, OrderStatus.OPEN)])
    await me.cancel_all_resting_orders()
    assert cancelled[0][1] == "EOD_AUTO_CANCEL"


def test_margin_is_released_by_going_through_cancel_order():
    """The whole point of reusing `cancel_order` — it releases the blocked
    margin. A bulk status update would strand it."""
    src = inspect.getsource(me.cancel_all_resting_orders)
    assert "cancel_order(" in src
    assert "release_margin" in inspect.getsource(me.cancel_order)


def test_positions_sl_tp_are_not_touched():
    """Clearing those would leave a carried position running with no stop."""
    src = inspect.getsource(me.cancel_all_resting_orders)
    assert "Position" not in src
    assert "stop_loss" not in src


def test_loop_fires_only_at_midnight_hour_and_once_a_day():
    src = inspect.getsource(me.eod_cancel_loop)
    assert "now.hour == 0" in src
    assert "_last_eod_cancel_day != day_key" in src


def test_loop_is_leader_gated_in_the_lifespan():
    """N workers each releasing margin for the same order would race."""
    import app.main as m

    src = inspect.getsource(m.lifespan)
    i = src.index("eod_cancel")
    assert "_leader_only" in src[i : i + 400]
