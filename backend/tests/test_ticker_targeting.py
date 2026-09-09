"""A ticker line aimed at one admin must not reach another admin's users.

The super admin writes a line and either sends it to the whole book or picks
admins one by one. Targeting is by ADMIN, not by user, so the visibility test
is "is any admin ABOVE this user in the selected set" - which means the walk
has to collect every admin-tier ancestor, not just the nearest one.

Two ways this goes wrong and both are silent:

  - a nearest-parent-only walk strands a client under a BROKER, so a line
    aimed at that broker's ADMIN never appears for them; and
  - combining `target_all` with a leftover `admin_ids` selection turns an
    all-hands line into a targeted one the moment somebody had once picked
    names, which nothing in the UI would show.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from beanie import PydanticObjectId

from app.api.v1.user import ticker as mod

A1 = PydanticObjectId()
A2 = PydanticObjectId()
BROKER = PydanticObjectId()
CLIENT = PydanticObjectId()


def line(*, target_all=False, admin_ids=(), text="x"):
    return SimpleNamespace(
        text=text, target_all=target_all, admin_ids=list(admin_ids)
    )


def test_all_hands_ignores_a_stale_selection():
    # Somebody picked A1, then flipped the line to "all". It must still run
    # for a user under A2 - the two modes are not combined.
    assert mod._line_visible(line(target_all=True, admin_ids=[A1]), {A2}) is True


def test_targeted_line_only_reaches_the_selected_admins_users():
    m = line(admin_ids=[A1])
    assert mod._line_visible(m, {A1, CLIENT}) is True
    assert mod._line_visible(m, {A2, CLIENT}) is False


def test_targeted_at_nobody_reaches_nobody():
    # Enabled but with an empty selection is a draft, not an all-hands line.
    assert mod._line_visible(line(admin_ids=[]), {A1}) is False


def _fake_users(rows):
    """Stand in for `User.get` over a fixed id -> row map."""

    async def get(uid):
        return rows.get(uid)

    return get


def test_the_walk_climbs_past_the_broker_to_the_admin(monkeypatch):
    # CLIENT -> BROKER -> A1. A line aimed at A1 must reach the client even
    # though the client's own row points at the broker.
    broker = SimpleNamespace(
        id=BROKER, assigned_broker_id=None, assigned_admin_id=A1
    )
    admin = SimpleNamespace(id=A1, assigned_broker_id=None, assigned_admin_id=None)
    client = SimpleNamespace(
        id=CLIENT, assigned_broker_id=BROKER, assigned_admin_id=A1
    )
    monkeypatch.setattr(
        mod.User, "get", _fake_users({BROKER: broker, A1: admin}), raising=False
    )

    mine = asyncio.run(mod._owning_admin_ids(client))
    assert {CLIENT, BROKER, A1} == mine
    assert mod._line_visible(line(admin_ids=[A1]), mine) is True
    assert mod._line_visible(line(admin_ids=[A2]), mine) is False


def test_a_chain_that_points_at_itself_terminates(monkeypatch):
    # A corrupted row pointing back up the chain must not spin forever.
    a = SimpleNamespace(id=A1, assigned_broker_id=A2, assigned_admin_id=None)
    b = SimpleNamespace(id=A2, assigned_broker_id=A1, assigned_admin_id=None)
    monkeypatch.setattr(mod.User, "get", _fake_users({A1: a, A2: b}), raising=False)

    assert asyncio.run(mod._owning_admin_ids(a)) == {A1, A2}
