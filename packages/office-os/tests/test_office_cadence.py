"""
Tests for the office-cadence signal.

Two real defects live here, both found on 2026-11-21:
  1. every autopilot round hung (the router lock self-deadlock), and the round
     files alone could not show it - a round that never finishes writes nothing;
  2. the first version of this collector then judged the append-only event log's
     LIFETIME totals, so after the fix it kept reporting the already-repaired
     hang. The window must be the running orchestrator's own rounds.
"""
import json
import time

import pytest

from core import office_audit, sources


def _events(tmp_path, *lines):
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return p


def _stamp(minutes_ago=0):
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - minutes_ago * 60))


@pytest.fixture
def events(tmp_path, monkeypatch):
    def _set(*lines):
        monkeypatch.setattr(office_audit, "EVENTS_PATH", _events(tmp_path, *lines))
        return office_audit._round_events()
    return _set


def test_all_rounds_hanging_is_detected(events):
    """The original defect: rounds start, nothing settles."""
    ev = events(
        {"event": "orchestrator_started"},
        {"event": "autopilot_round_started", "round": _stamp(120)},
        {"event": "autopilot_round_started", "round": _stamp(90)},
        {"event": "autopilot_round_started", "round": _stamp(60)},
    )
    assert ev["settled"] == 2 and ev["lost"] == 2, "two settled rounds, both lost"
    assert ev["in_flight"] == _stamp(60)


def test_restart_does_not_inherit_the_old_hangs(events):
    """The regression: a fixed hang must not be reported forever."""
    ev = events(
        {"event": "orchestrator_started"},
        {"event": "autopilot_round_started", "round": _stamp(300)},
        {"event": "autopilot_round_started", "round": _stamp(270)},
        {"event": "orchestrator_started"},                        # the restart
        {"event": "autopilot_round_started", "round": _stamp(10)},
        {"event": "autopilot_round_finished", "round": _stamp(10)},
    )
    assert ev["started"] == 3, "all-time count still reports the history"
    assert ev["this_process"] == 1 and ev["lost"] == 0, "but the verdict is this process only"
    assert ev["newest_outcome"] == "finished"


def test_a_failed_round_is_settled_not_lost(events):
    ev = events(
        {"event": "orchestrator_started"},
        {"event": "autopilot_round_started", "round": _stamp(40)},
        {"event": "autopilot_round_failed", "round": _stamp(40)},
        {"event": "autopilot_round_started", "round": _stamp(5)},
    )
    assert ev["lost"] == 0, "a round that failed did not hang: it reported"


def test_in_flight_round_is_dated_from_its_id(events):
    ev = events(
        {"event": "orchestrator_started"},
        {"event": "autopilot_round_started", "round": _stamp(75)},
    )
    assert 70 < ev["in_flight_age_min"] < 80


def test_missing_event_log_is_not_ok(tmp_path, monkeypatch):
    """Unknown is not ok: an unreadable log must not read as healthy."""
    monkeypatch.setattr(office_audit, "EVENTS_PATH", tmp_path / "nope.jsonl")
    assert office_audit._round_events() is None
    monkeypatch.setattr(office_audit, "cadence", lambda: {
        "enabled": True, "interval_min": 30, "rounds_dir": str(tmp_path),
        "rounds_dir_exists": True, "round_files": 1, "latest_age_min": 1.0,
        "events": None, "events_path": str(tmp_path / "nope.jsonl"), "departments": 10,
        "max_rounds_per_day": 24, "rounds_today": 1, "budget_spent": False,
        "summary_stamped": True,
    })
    result = sources.office_cadence()
    assert not result["ok"] and "unverifiable" in result["problems"][0]


def test_disabled_autopilot_is_not_a_problem(monkeypatch):
    monkeypatch.setattr(office_audit, "cadence", lambda: {
        "enabled": False, "interval_min": 30, "rounds_dir": "/x",
        "rounds_dir_exists": False, "round_files": 0, "latest_age_min": None,
        "events": None, "events_path": "/x/events.jsonl", "departments": 10,
        "max_rounds_per_day": 24, "rounds_today": 1, "budget_spent": False,
        "summary_stamped": True,
    })
    assert sources.office_cadence()["ok"]


def _cadence_stub(**over):
    base = {
        "enabled": True, "interval_min": 30, "rounds_dir": "/x",
        "rounds_dir_exists": True, "round_files": 47, "latest_age_min": 572.0,
        "events": {"started": 57, "finished": 47, "failed": 0, "this_process": 47,
                   "settled": 47, "lost": 0, "newest_round": "20261122-113856",
                   "newest_outcome": "finished", "in_flight": None,
                   "in_flight_age_min": None},
        "events_path": "/x/events.jsonl", "departments": 10,
        "max_rounds_per_day": 24, "rounds_today": 24, "budget_spent": True,
        "summary_stamped": True,
    }
    base.update(over)
    return lambda: base


def test_spent_daily_budget_is_not_a_stall(monkeypatch):
    """max_rounds_per_day=24 stops the autopilot for the day on purpose; a stale
    newest round after that is correct behaviour, not a problem."""
    monkeypatch.setattr(office_audit, "cadence", _cadence_stub())
    r = sources.office_cadence()
    assert r["ok"], r["problems"]
    assert "budget SPENT" in r["summary"]


def test_stale_rounds_with_budget_left_is_still_a_stall(monkeypatch):
    """The same staleness, but with budget remaining, must still be reported."""
    monkeypatch.setattr(office_audit, "cadence",
                        _cadence_stub(rounds_today=3, budget_spent=False))
    r = sources.office_cadence()
    assert not r["ok"]
    assert "over 3x" in r["problems"][0]
