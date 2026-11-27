"""Doctor system health-check tests (Interpretation D: health gates).

Every external dependency of dost_main.doctor() is mocked so each of the
health gates is tested deterministically: no network, no launchctl, no real
git state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from dost import dost_main


class FakeResp:
    """Minimal urllib response: context manager with .read() and .status."""

    def __init__(self, body=b"{}"):
        self.body = body
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class FakeRun:
    def __init__(self, stdout=""):
        self.stdout = stdout

    def __call__(self, *args, **kwargs):
        return self


def _healthy(monkeypatch, tmp_path):
    """Stub every external dependency of doctor() into a passing state."""
    monkeypatch.setattr(dost_main, "_fetch_dispatcher_status", lambda: {"error_rate": 1.0})
    monkeypatch.setattr(dost_main, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        dost_main, "_metrics_freshness", lambda st: (True, "data_ready=True data age=10s")
    )
    monkeypatch.setattr(dost_main, "_dispatcher_log_age_sec", lambda: None)
    monkeypatch.setattr(dost_main, "_plists_loaded", lambda: (True, "all loaded"))
    monkeypatch.setattr(
        dost_main, "summarize_provider_pools", lambda pools, probe: (True, "all pools healthy")
    )
    monkeypatch.setattr(dost_main, "probe_local_pools", lambda timeout=3.0: {})
    monkeypatch.setattr(dost_main, "_load_findings_store", lambda: {"findings": []})
    monkeypatch.setattr(dost_main, "_daily_cost_check", lambda pnl_path: (True, "cap ok"))
    monkeypatch.setattr(dost_main, "_cost_anomaly_check", lambda pnl_path: (True, "anomaly ok"))
    monkeypatch.setattr(dost_main, "ALERT_WEBHOOK_URL", None)
    monkeypatch.setattr(dost_main, "COMPANY_DIR", tmp_path)  # no .git/index.lock here

    def fake_urlopen(url, timeout=4):
        if "11434" in url:
            return FakeResp(b'{"models": []}')
        return FakeResp(b'{"provider_pools": {}, "free_ceiling": {"calls_per_day_ceiling": 1000, "calls_today": 100, "headroom_pct": 90}}')

    monkeypatch.setattr(dost_main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(dost_main.subprocess, "run", FakeRun(stdout=""))


def test_doctor_all_checks_pass_exit_zero(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)

    board, code = dost_main.doctor()

    assert code == 0
    assert "All checks passed." in board


def test_doctor_dispatcher_unreachable_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    monkeypatch.setattr(dost_main, "_fetch_dispatcher_status", lambda: None)

    board, code = dost_main.doctor()

    assert code == 1
    assert "Dispatcher reachable" in board
    assert "One or more checks FAILED." in board


def test_doctor_metrics_stale_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dost_main, "_metrics_freshness", lambda st: (False, "data_ready=False data age=unknown")
    )

    board, code = dost_main.doctor()

    assert code == 1
    assert "Metrics fresh" in board


def test_doctor_plists_not_loaded_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dost_main, "_plists_loaded", lambda: (False, "not loaded: com.aryan.office-os.plist")
    )

    board, code = dost_main.doctor()

    assert code == 1
    assert "Plists loaded" in board


def test_doctor_ollama_unreachable_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)

    def fake(url, timeout=4):
        if "11434" in url:
            raise RuntimeError("connection refused")
        return FakeResp()

    monkeypatch.setattr(dost_main.urllib.request, "urlopen", fake)

    board, code = dost_main.doctor()

    assert code == 1
    assert "qwen_local / ollama reachable" in board


def test_doctor_provider_pools_unhealthy_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dost_main,
        "summarize_provider_pools",
        lambda pools, probe: (False, "mlx pool down, fallback exhausted"),
    )

    board, code = dost_main.doctor()

    assert code == 1
    assert "Provider pools healthy" in board


def test_doctor_untracked_git_files_ok_tracked_changes_fail(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)

    monkeypatch.setattr(dost_main.subprocess, "run", FakeRun(stdout="?? new-file.py\n"))
    board, code = dost_main.doctor()
    assert code == 0, board

    monkeypatch.setattr(
        dost_main.subprocess, "run", FakeRun(stdout=" M dost/dost_main.py\n?? new-file.py\n")
    )
    board, code = dost_main.doctor()
    assert code == 1
    assert "Git status clean-ish" in board


def test_doctor_index_lock_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    (tmp_path / ".git").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git" / "index.lock").write_text("")

    board, code = dost_main.doctor()

    assert code == 1
    assert "No .git/index.lock" in board


def test_doctor_anomaly_high_error_rate_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    monkeypatch.setattr(dost_main, "_fetch_dispatcher_status", lambda: {"error_rate": 7.5})

    board, code = dost_main.doctor()

    assert code == 1
    assert "Anomaly alerts" in board
    assert "error rate 7.5%" in board


def test_doctor_pool_cooldown_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)

    def fake(url, timeout=4):
        if "8083/metrics" in url:
            return FakeResp(
                json.dumps({"provider_pools": {"mlx": {"cooldown_remaining": 900}}}).encode()
            )
        return FakeResp()

    monkeypatch.setattr(dost_main.urllib.request, "urlopen", fake)

    board, code = dost_main.doctor()

    assert code == 1
    assert "mlx cooling 15min" in board


def test_doctor_quota_low_headroom_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)

    def fake(url, timeout=4):
        if "8083/metrics" in url:
            return FakeResp(
                json.dumps(
                    {
                        "provider_pools": {},
                        "free_ceiling": {
                            "calls_per_day_ceiling": 1000,
                            "calls_today": 950,
                            "headroom_pct": 5,
                        },
                    }
                ).encode()
            )
        return FakeResp()

    monkeypatch.setattr(dost_main.urllib.request, "urlopen", fake)

    board, code = dost_main.doctor()

    assert code == 1
    assert "Quota burn projection" in board
    assert "LOW HEADROOM" in board


def test_doctor_stale_findings_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(
        dost_main,
        "_load_findings_store",
        lambda: {
            "findings": [
                {
                    "verification_status": "pending",
                    "date": old,
                    "agent": "research-analyst",
                    "claim": "stale claim",
                }
            ]
        },
    )

    board, code = dost_main.doctor()

    assert code == 1
    assert "Anomaly alerts" in board
    assert "findings pending >30 days" in board


def test_doctor_daily_cost_cap_fail_exit_one(tmp_path, monkeypatch):
    _healthy(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dost_main, "_daily_cost_check", lambda pnl_path: (False, "cap breached: $50 > $10")
    )

    board, code = dost_main.doctor()

    assert code == 1
    assert "Daily cost cap" in board
