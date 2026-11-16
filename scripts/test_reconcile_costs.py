"""Tests for the costs reconciliation union merge.

The merge is the step that can do real damage to historical accounting data,
so these pin the three properties that make it safe: it must never lose a
record, never duplicate one, and never invent a value.
"""
import importlib.util
import os
import sys
import tempfile

spec = importlib.util.spec_from_file_location(
    "rc", os.path.join(os.path.dirname(__file__), "..", "scripts", "reconcile_costs.py"))
rc = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(rc)
except SystemExit:
    pass


def rec(ts, tid, cost):
    return {"agentId": "a", "costUsd": cost, "model": "m", "provider": "nvidia",
            "taskId": tid, "timestamp": ts}


def test_union_keeps_records_from_both_sides():
    live = {"daily": 1.0, "monthly": 2.0, "records": [rec("2026-01-01T00:00:00Z", "t1", 0.1)]}
    archive = {"daily": 0.0, "monthly": 0.0, "records": [rec("2026-01-02T00:00:00Z", "t2", 0.2)]}
    merged, added = rc.merge_agent(live, archive)
    assert added == 1
    assert len(merged["records"]) == 2, "union must keep both sides"


def test_union_does_not_duplicate_a_shared_record():
    shared = rec("2026-01-01T00:00:00Z", "t1", 0.1)
    live = {"daily": 0.0, "monthly": 0.0, "records": [shared]}
    archive = {"daily": 0.0, "monthly": 0.0, "records": [shared]}
    merged, added = rc.merge_agent(live, archive)
    assert added == 0
    assert len(merged["records"]) == 1, "a record present in both must appear once"


def test_union_keeps_a_live_only_record():
    """The archive is not a superset; records only live has must survive."""
    live = {"daily": 0.0, "monthly": 0.0, "records": [rec("2026-09-29T00:00:00Z", "t9", 0.5)]}
    archive = {"daily": 0.0, "monthly": 0.0, "records": [rec("2026-01-01T00:00:00Z", "t1", 0.1)]}
    merged, _ = rc.merge_agent(live, archive)
    ids = {r["taskId"] for r in merged["records"]}
    assert "t9" in ids, "a record only live had was discarded"


def test_merge_is_idempotent():
    live = {"daily": 0.0, "monthly": 0.0, "records": [rec("2026-01-01T00:00:00Z", "t1", 0.1)]}
    archive = {"daily": 0.0, "monthly": 0.0, "records": [rec("2026-01-02T00:00:00Z", "t2", 0.2)]}
    once, _ = rc.merge_agent(live, archive)
    twice, added2 = rc.merge_agent(once, archive)
    assert added2 == 0, "re-running the merge added records again"
    assert len(twice["records"]) == len(once["records"])


def test_accumulators_take_the_larger_value_and_are_never_nulled():
    live = {"daily": None, "monthly": None, "records": []}
    archive = {"daily": 5.0, "monthly": 9.0, "records": []}
    merged, _ = rc.merge_agent(live, archive)
    assert merged["daily"] == 5.0 and merged["monthly"] == 9.0

    live2 = {"daily": 7.0, "monthly": 2.0, "records": []}
    merged2, _ = rc.merge_agent(live2, archive)
    assert merged2["daily"] == 7.0, "the larger daily must win"
    assert merged2["monthly"] == 9.0, "the larger monthly must win"


def test_records_are_ordered_by_timestamp():
    live = {"records": [rec("2026-03-01T00:00:00Z", "b", 0.1)], "daily": 0, "monthly": 0}
    archive = {"records": [rec("2026-01-01T00:00:00Z", "a", 0.1),
                           rec("2026-02-01T00:00:00Z", "c", 0.1)], "daily": 0, "monthly": 0}
    merged, _ = rc.merge_agent(live, archive)
    ts = [r["timestamp"] for r in merged["records"]]
    assert ts == sorted(ts), "merged records must be chronological, got %s" % ts


def test_null_costusd_history_is_carried_through_not_recomputed():
    """The NaN era left costUsd null. Recomputing would invent history."""
    old = {"agentId": "a", "costUsd": None, "model": "m", "provider": "nvidia",
           "taskId": "t1", "timestamp": "2026-01-01T00:00:00Z"}
    live = {"daily": 0, "monthly": 0, "records": [old]}
    merged, _ = rc.merge_agent(live, {"daily": 0, "monthly": 0, "records": []})
    assert merged["records"][0]["costUsd"] is None, "a null historical cost was rewritten"
