"""Tests for the hourly floor rollup.

The failure mode for an operations summary is not a crash, it is a green
report. If a dead agent reads as healthy, or an agent with no session reads as
fine, the summary is worse than nothing because it is believed. So the tests
below are mostly negative: they assert that bad states surface, and that an
unreadable input yields UNKNOWN rather than a clean bill.
"""
import datetime
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "rollup_floor_summary.py")
SCRIPT = os.path.abspath(SCRIPT)

spec = importlib.util.spec_from_file_location("rollup", SCRIPT)
rollup = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(rollup)
except SystemExit:
    pass


NOW = 1800000000.0


def iso(offset_s):
    return (datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc)
            + datetime.timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def use_fixtures(registry, sessions):
    d = tempfile.mkdtemp()
    reg = os.path.join(d, "registry.json")
    ses = os.path.join(d, "sessions.json")
    with open(reg, "w") as f:
        json.dump(registry, f)
    with open(ses, "w") as f:
        json.dump(sessions, f)
    rollup.REGISTRY = reg
    rollup.SESSIONS = ses
    return d


def test_sessions_wrapped_under_a_key_still_parse():
    """The real file is {"sessions": [...]}. Reading it as a flat dict makes
    every agent look like it has no session, which is a fleet-wide false
    all-clear rather than a crash."""
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"id": "a1", "floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0),
                       "current_task_id": "t1"}]},
    )
    r = rollup.build(NOW)
    assert r["totals"]["healthy"] == 1, "wrapped sessions were not parsed"
    assert r["totals"]["in_flight"] == 1


def test_a_stale_heartbeat_is_stale_not_healthy():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"id": "a1", "floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(-3600),
                       "current_task_id": None}]},
    )
    r = rollup.build(NOW)
    assert r["totals"]["stale"] == 1, "an hour-old heartbeat was called healthy"
    assert r["totals"]["healthy"] == 0
    assert "STALE" in r["floors"][0]["agents_detail"]["a1"]


def test_a_fresh_heartbeat_is_healthy():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"id": "a1", "floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(-10),
                       "current_task_id": None}]},
    )
    r = rollup.build(NOW)
    assert r["totals"]["healthy"] == 1
    assert r["totals"]["stale"] == 0


def test_a_missing_heartbeat_is_unknown_not_healthy():
    """Absent evidence is not evidence of health. It must be its own verdict."""
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"id": "a1", "floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": None}]},
    )
    r = rollup.build(NOW)
    assert r["totals"]["unknown_heartbeat"] == 1
    assert r["totals"]["healthy"] == 0, "unknown heartbeat was counted as healthy"


def test_a_registered_agent_with_no_session_is_visible():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"id": "a1", "floor": "f1"}}},
        {"sessions": []},
    )
    r = rollup.build(NOW)
    assert r["floors"][0]["agents_detail"]["a1"] == "NO_SESSION"
    assert r["totals"]["healthy"] == 0


def test_an_agent_with_a_session_but_no_registry_entry_is_unowned():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"id": "a1", "floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)},
                      {"agent_id": "ghost", "last_heartbeat": iso(0)}]},
    )
    r = rollup.build(NOW)
    assert r["unowned_agents_with_sessions"] == ["ghost"]


def test_floors_are_grouped_from_the_registry_ownership_map():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}, "a2": {"floor": "f1"},
                    "b1": {"floor": "polymarket"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)},
                      {"agent_id": "a2", "last_heartbeat": iso(0)},
                      {"agent_id": "b1", "last_heartbeat": iso(0)}]},
    )
    r = rollup.build(NOW)
    by = {f["floor"]: f for f in r["floors"]}
    assert by["f1"]["agents"] == 2
    assert by["polymarket"]["agents"] == 1


def test_render_flags_a_floor_that_needs_attention():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(-3600)}]},
    )
    out = rollup.render(rollup.build(NOW))
    assert "attention" in out, "a stale floor was not flagged in the rendered summary"
