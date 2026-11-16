"""Mini bridge tests. Real Hive in a temp folder; ssh is replaced by a fake runner."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from core import mini_bridge as mb
from core.hive import Hive


class FakeRunner:
    """Records every remote command. `replies` maps a substring of the command to (rc, out, err)."""

    def __init__(self, replies=None, default=(0, "", "")):
        self.calls = []
        self.stdins = []
        self.replies = replies or {}
        self.default = default

    def run(self, remote_cmd, stdin_text=None):
        self.calls.append(remote_cmd)
        self.stdins.append(stdin_text)
        for key, reply in self.replies.items():
            if key in remote_cmd:
                return reply
        return self.default


@pytest.fixture
def hive(tmp_path):
    return Hive(root=str(tmp_path))


@pytest.fixture
def stop(tmp_path):
    return tmp_path / "STOP"


def mini_task(hive, mtype="summary", title="Summarise the week", desc="Keep it short."):
    return hive.create_task(title, desc, metadata={"target": "mini", "mini_type": mtype})


def test_unreachable_mini_keeps_task_pending_not_failed(hive, stop):
    t = mini_task(hive)
    runner = FakeRunner(default=(None, "", "timed out"))
    report = mb.MiniBridge(hive, runner, stop).cycle()
    got = hive.get_task(t["id"])
    assert got["status"] == "pending"
    assert "mini_delivered_at" not in got["metadata"]
    assert report["queued"] == 1


def test_delivery_writes_json_atomically_and_marks_delivered(hive, stop):
    t = mini_task(hive)
    runner = FakeRunner()
    mb.MiniBridge(hive, runner, stop).cycle()
    cmd = runner.calls[0]
    assert f"{t['id']}.json.tmp" in cmd and "mv " in cmd  # write temp, then rename
    body = json.loads(runner.stdins[0])
    assert body["id"] == t["id"] and body["type"] == "summary"
    assert "Summarise the week" in body["prompt"]
    got = hive.get_task(t["id"])
    assert got["metadata"]["mini_state"] == "delivered"
    assert got["status"] == "pending"  # still owned by the bridge


@pytest.mark.parametrize("bad_id", ["x;rm -rf ~", "../../etc", "a b", "", "-x"])
def test_unsafe_ids_are_never_sent(bad_id):
    assert not mb.ID_RE.match(bad_id)


def test_disallowed_type_is_refused_and_marked_failed(hive, stop):
    t = mini_task(hive, mtype="deploy")
    runner = FakeRunner()
    mb.MiniBridge(hive, runner, stop).cycle()
    assert runner.calls == []
    got = hive.get_task(t["id"])
    assert got["status"] == "failed" and "not allowed" in got["error"]


def test_completed_verdict_closes_task_done(hive, stop):
    t = mini_task(hive)
    verdict = json.dumps({"status": "completed", "preview": "A short summary.", "stored": True,
                          "jev_judgment": None, "finished_at": "2026-11-15T10:00:00+00:00"})
    runner = FakeRunner(default=(0, "", ""))
    bridge = mb.MiniBridge(hive, runner, stop)
    bridge.cycle()  # deliver
    runner.replies = {f"outbox/{t['id']}.json": (0, verdict, "")}
    report = bridge.cycle()  # collect
    got = hive.get_task(t["id"])
    assert got["status"] == "done"
    assert got["result"]["preview"] == "A short summary."
    assert (t["id"], "done") in report["collected"]


def test_rejected_verdict_marks_failed_with_reason(hive, stop):
    t = mini_task(hive)
    verdict = json.dumps({"status": "rejected", "reason": "unknown type 'x'"})
    runner = FakeRunner(default=(0, "", ""))
    bridge = mb.MiniBridge(hive, runner, stop)
    bridge.cycle()
    runner.replies = {f"outbox/{t['id']}.json": (0, verdict, "")}
    bridge.cycle()
    got = hive.get_task(t["id"])
    assert got["status"] == "failed" and "rejected" in got["error"]


def test_no_verdict_yet_leaves_task_pending(hive, stop):
    t = mini_task(hive)
    runner = FakeRunner(default=(0, "", ""))
    bridge = mb.MiniBridge(hive, runner, stop)
    bridge.cycle()
    bridge.cycle()  # outbox empty
    assert hive.get_task(t["id"])["status"] == "pending"


def test_unknown_verdict_ids_are_never_read(hive, stop):
    t = mini_task(hive)
    runner = FakeRunner(default=(0, "", ""))
    bridge = mb.MiniBridge(hive, runner, stop)
    bridge.cycle()
    bridge.cycle()
    reads = [c for c in runner.calls if "outbox/" in c]
    assert reads and all(t["id"] in c for c in reads)


def test_stop_file_halts_all_mini_traffic(hive, stop):
    mini_task(hive)
    stop.write_text("")
    runner = FakeRunner()
    report = mb.MiniBridge(hive, runner, stop).cycle()
    assert runner.calls == []
    assert "STOP" in report["skipped"]


def test_orchestrator_skips_mini_tasks_in_auto_assign(hive, stop):
    t = mini_task(hive)
    pending = [x for x in hive.list_tasks(status="pending")
               if (x.get("metadata") or {}).get("target") != "mini"]
    assert all(x["id"] != t["id"] for x in pending)


def test_task_with_no_verdict_times_out_to_failed(hive, stop):
    t = mini_task(hive)
    old = (datetime.now(timezone.utc) - timedelta(hours=mb.VERDICT_TIMEOUT_HOURS + 1)).isoformat()
    hive.update_task(t["id"], metadata={**t["metadata"], "mini_delivered_at": old, "mini_state": "delivered"})
    runner = FakeRunner(default=(0, "", ""))
    mb.MiniBridge(hive, runner, stop).cycle()
    got = hive.get_task(t["id"])
    assert got["status"] == "failed" and "no verdict" in got["error"]


def test_recent_delivery_without_verdict_stays_pending(hive, stop):
    t = mini_task(hive)
    recent = datetime.now(timezone.utc).isoformat()
    hive.update_task(t["id"], metadata={**t["metadata"], "mini_delivered_at": recent, "mini_state": "delivered"})
    runner = FakeRunner(default=(0, "", ""))
    mb.MiniBridge(hive, runner, stop).cycle()
    assert hive.get_task(t["id"])["status"] == "pending"
