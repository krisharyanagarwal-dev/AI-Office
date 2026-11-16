"""Tests for check_llm_success_rate.

A health check that always fails is as useless as one that always passes, and
worse than no check at all, because it trains operators to ignore it. These
drive both directions over fixture logs, plus the negative cases that matter
for a measurement tool: an empty population must be UNVERIFIABLE, not OK, and
a fleet that is busy but failing must not be reported as healthy.
"""
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "scripts", "check_llm_success_rate.py")
SCRIPT = os.path.abspath(SCRIPT)
PY = sys.executable


def run(dirpath, *extra):
    return subprocess.run([PY, SCRIPT, "--pattern", os.path.join(dirpath, "*.log")] + list(extra),
                          capture_output=True, text=True)


def write_logs(tmp, body, n=1):
    for i in range(n):
        with open(os.path.join(tmp, "agent-%d_manager.log" % i), "w") as f:
            f.write(body)


OK_LINE = "[a] [INFO] LLM Response: done\n"
FAIL_LINE = "[a] [LLMClient] Provider nvidia failed: NVIDIA HTTP 429: slow down\n"
EXHAUSTED = "[a] [INFO] executor llm_error All LLM providers failed [attempted: freeHarness,nvidia]\n"
NOWORK = "[a] [INFO] executor finished: status=llm_error turns=0 tools=0 edits=0\n"


def test_healthy_fleet_is_clean():
    tmp = tempfile.mkdtemp()
    write_logs(tmp, OK_LINE * 40 + FAIL_LINE, n=3)
    r = run(tmp)
    assert r.returncode == 0, "healthy fleet should be clean, got %d\n%s" % (r.returncode, r.stdout)
    assert "OK" in r.stdout


def test_total_failure_is_a_finding():
    tmp = tempfile.mkdtemp()
    write_logs(tmp, EXHAUSTED * 30 + OK_LINE, n=3)
    r = run(tmp)
    assert r.returncode == 1, "total provider failure must be a finding, got %d" % r.returncode
    assert "FAIL" in r.stdout


def test_busy_but_failing_is_not_healthy():
    """Request volume must never be mistaken for success."""
    tmp = tempfile.mkdtemp()
    # 200 attempts, 20 succeed: high volume, low success.
    write_logs(tmp, (OK_LINE + EXHAUSTED) * 20 + OK_LINE, n=5)
    r = run(tmp)
    assert r.returncode == 1, "high volume with low success must still fail"
    assert "measured from executor outcomes" in r.stdout


def test_empty_population_is_unverifiable_not_ok():
    tmp = tempfile.mkdtemp()
    r = run(tmp)
    assert r.returncode == 2, "no attempts must be unverifiable (2), got %d" % r.returncode
    assert "UNVERIFIABLE" in r.stdout


def test_no_work_turns_are_counted():
    tmp = tempfile.mkdtemp()
    write_logs(tmp, OK_LINE * 30 + EXHAUSTED * 2 + NOWORK * 2, n=2)
    r = run(tmp)
    assert "turns finished with no work" in r.stdout
    line = [l for l in r.stdout.splitlines() if "no work" in l][0]
    assert not line.strip().endswith("0"), "no-work turns were not counted"


def test_threshold_is_configurable():
    tmp = tempfile.mkdtemp()
    # 80% success: fine at 70 floor, a finding at 90 floor.
    write_logs(tmp, OK_LINE * 16 + EXHAUSTED * 4, n=2)
    assert run(tmp, "--min-rate", "70").returncode == 0
    assert run(tmp, "--min-rate", "90").returncode == 1
