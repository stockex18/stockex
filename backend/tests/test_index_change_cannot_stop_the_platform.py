"""Changing an index must never refuse to start the platform.

MongoDB rejects an index whose NAME exists with different options
(`IndexKeySpecsConflict`, code 86) and Beanie lets that kill the boot. On
23 Sept, making email/mobile unique PER ROLE collided with the old
platform-wide `email_1`: the app would not start and the feed was out for
minutes, mid-session, for a one-line schema edit.

A heal already existed — a hard-coded list of two index names that marked
itself done for ever, so it could only ever fix the two conflicts somebody had
already hit. It is generic now, and it runs on every boot.
"""

from __future__ import annotations

import inspect

from app.core import database as db


def test_the_reconcile_asks_the_models_rather_than_a_hard_coded_list():
    s = inspect.getsource(db._reconcile_conflicting_indexes)
    assert "_models = _document_models()" in s
    assert "index_information()" in s


def test_it_only_drops_on_a_real_mismatch():
    """A needless drop costs an index rebuild — on a normal boot this must
    read metadata and change nothing."""
    s = inspect.getsource(db._reconcile_conflicting_indexes)
    assert "if same_key and same_unique and same_partial:" in s
    assert "continue" in s.split("if same_key and same_unique and same_partial:")[1][:40]


def test_it_compares_every_option_mongo_conflicts_on():
    s = inspect.getsource(db._reconcile_conflicting_indexes)
    for probe in ("same_key", "same_unique", "same_partial"):
        assert probe in s, probe
    assert "partialFilterExpression" in s


def test_an_index_that_does_not_exist_yet_is_left_to_beanie():
    s = inspect.getsource(db._reconcile_conflicting_indexes)
    assert "if current is None:" in s


def test_it_never_blocks_the_boot():
    s = inspect.getsource(db._run_schema_heal_once)
    assert "index_reconcile_failed_continuing" in s
    body = inspect.getsource(db._reconcile_conflicting_indexes)
    # Listing a collection's indexes, and dropping one, are both allowed to
    # fail without taking the platform with them.
    assert body.count("except Exception") >= 2


def test_it_runs_once_per_boot_not_once_ever():
    """The old barrier returned early for ever once `done` was set, so a new
    conflict could never be healed — which is precisely how the outage
    happened."""
    s = inspect.getsource(db._run_schema_heal_once)
    assert "fin > now - _SCHEMA_HEAL_STALE_AFTER" in s
    assert '"done": True,\n                     "finished_at"' in s


def test_a_crashed_claim_is_still_reclaimable():
    s = inspect.getsource(db._run_schema_heal_once)
    assert '{"done": {"$ne": True},' in s
    assert '"started_at": {"$lt": now - _SCHEMA_HEAL_STALE_AFTER}}' in s


def test_the_drops_stay_behind_the_one_worker_barrier():
    """A drop racing a sibling's index build is IndexBuildAborted (code 276),
    which is the reason the barrier exists at all."""
    s = inspect.getsource(db._run_schema_heal_once)
    assert s.index("if claimed:") < s.index("_reconcile_conflicting_indexes(db)")
    assert "Follower: wait for the leader to finish" in s


def test_it_runs_before_beanie_builds_anything():
    s = inspect.getsource(db.init_database)
    assert s.index("_run_schema_heal_once") < s.index("init_beanie(")
