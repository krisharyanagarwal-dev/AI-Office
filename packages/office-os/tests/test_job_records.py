"""
Tests for the job-records collector - the laptop's view of what the mini produced.

Two behaviours are pinned, and they pull in opposite directions:

  * nothing is scheduled yet, so an OLD record is not a fault. This collector's
    three predecessors each shipped a false positive of exactly that shape
    (lifetime totals, a spent daily budget, pre-restart hangs), so staleness is
    deliberately NOT a problem here;
  * rejects piling up since a job's last accepted answer IS a fault, and the only
    thing in the whole ladder that asks for an expensive model. That is the
    escalation signal from docs/compile-and-run.md section 4.
"""
import pytest

from core import sources

HEALTHY_JOB = {
    "records": 6, "failures": 1, "last_record_ts": "2026-11-22T22:04:26",
    "last_record_age_min": 18.2, "rejects_since_success": 0,
    "last_failure_stage": None, "last_failure_problem": None,
    "model": "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4",
    "last_answer": {"boundary_verdict": "PASS", "exposure_verdict": "NO_EVIDENCE"},
}


@pytest.fixture
def records(monkeypatch):
    def _set(job_output):
        monkeypatch.setattr(sources, "_mini", lambda: {"job_output": job_output})
        return sources.job_records()
    return _set


def test_the_real_state_today_is_ok(records):
    """6 accepted, 1 failure that predates the last success."""
    r = records({"risk-boundary-gate": dict(HEALTHY_JOB)})
    assert r["ok"], r["problems"]
    assert "6 records, 1 failures" in r["summary"]


def test_an_old_record_is_not_a_problem(records):
    """Nothing schedules this job yet. Age alone must not be reported."""
    r = records({"risk-boundary-gate": dict(HEALTHY_JOB, last_record_age_min=4000.0)})
    assert r["ok"], r["problems"]


def test_rejects_since_success_escalate(records):
    r = records({"risk-boundary-gate": dict(
        HEALTHY_JOB, rejects_since_success=3, last_failure_stage="schema",
        last_failure_problem="field open_positions: not an integer (got [])")})
    assert not r["ok"]
    assert "compile pass" in r["problems"][0]
    assert "schema" in r["problems"][0]


def test_one_reject_does_not_escalate(records):
    """A single bad run is noise; the threshold comes from the job spec."""
    r = records({"risk-boundary-gate": dict(HEALTHY_JOB, rejects_since_success=1)})
    assert r["ok"], r["problems"]


def test_a_job_that_never_worked_is_reported(records):
    r = records({"new-job": dict(HEALTHY_JOB, records=0, rejects_since_success=2,
                                 last_answer=None)})
    assert not r["ok"]
    assert "never worked" in r["problems"][0]


def test_no_output_yet_is_not_a_fault(records):
    """A system still being built has produced nothing. That is a true statement."""
    r = records({"dir_error": "FileNotFoundError"})
    assert r["ok"]
    assert "no job has produced output yet" in r["summary"]


def test_an_unreadable_dir_is_a_fault(records):
    r = records({"dir_error": "PermissionError"})
    assert not r["ok"]
    assert "unreadable" in r["problems"][0]


def test_unreachable_mini_fails_closed(monkeypatch):
    monkeypatch.setattr(sources, "_mini", lambda: {"error": "ssh timed out"})
    assert not sources.job_records()["ok"]


def test_missing_block_fails_closed(monkeypatch):
    """The mini answered but ran an older script: unknown is not ok."""
    monkeypatch.setattr(sources, "_mini", lambda: {"jobs": {}})
    assert not sources.job_records()["ok"]


def test_threshold_comes_from_the_job_spec():
    """The shipped spec must carry a machine-readable threshold, not just prose."""
    thresholds = sources._escalation_thresholds()
    assert thresholds.get("risk-boundary-gate") == 3
