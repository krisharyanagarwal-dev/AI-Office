"""
Offline self-test for dost/jarvis.py. No network, no real fleet, no model calls.
Runs: python3 dost/jarvis_selftest.py
"""
from __future__ import annotations

import sys
import shutil
import json
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jarvis  # noqa: E402  (needed to stub dispatch below)
from jarvis import route, execute, ToolCall, build_cached_context, resolve_pending, store_pending

import proactive_monitor  # noqa: E402

# Stub fleet dispatch so this selftest can never write to HIVE_DIR.
# Mimics the unconfirmed path: restates intent, asks for "yes", writes nothing.
def _stub_dispatch(text, confirmed, dry_run):
    if not confirmed and dry_run:
        return 'I\'d dispatch this to the assistant department as "{0}". Say "yes" to confirm.'.format(text[:70])
    return "Stubbed dispatch: {0}".format(text[:50])

jarvis.dispatch = _stub_dispatch

# Stub iMessage delivery so the selftest never sends a real message.
# Respects IMSG_PATH so the degraded test can simulate a missing binary.
_SENT = []
def _stub_send_imsg(text: str) -> bool:
    if proactive_monitor.IMSG_PATH == "/nonexistent/imsg":
        return False
    _SENT.append(text)
    return True

proactive_monitor._send_imsg = _stub_send_imsg

FAILS = 0


def check(label, got, want):
    global FAILS
    ok = got == want
    if not ok:
        FAILS += 1
    print(("PASS" if ok else "FAIL"), label, "->", repr(got)[:90], "(want", repr(want)[:90] + ")" if not ok else "")


def test_router_read_tools():
    print("--- router: read tools ---")
    check("fleet", route("how's the fleet"), ToolCall("fleet_status"))
    check("dispatcher", route("what's the dispatcher doing"), ToolCall("fleet_status"))
    check("recent tasks", route("recent tasks"), ToolCall("recent_tasks"))
    check("alerts", route("any alerts?"), ToolCall("alerts"))
    check("recall", route("what did we say last time"), ToolCall("recall"))
    check("system health", route("system health"), ToolCall("fleet_status"))
    check("plain chat", route("hey how are you"), None)
    check("plain chat 2", route("write me a python script"), None)


def test_router_negative():
    print("--- router: negative (plain chat, must not dispatch) ---")
    negative = [
        "do you like tea",
        "do you know what time it is",
        "start over",
        "run with it",
        "check out this song",
        "execute order 66",
        "start fresh",
        "what should I do",
        "is everything ok",
        "check the system",
        "run an audit",
        "audit the system",
        "audit",
        "my cup of tea",
        # imperative "remember X" is a memory WRITE — must fall through to plain chat
        "remember I prefer oolong",
        "remember this",
    ]
    for phrase in negative:
        check("negative: " + phrase, route(phrase), None)


def test_router_remember():
    print("--- router: remember split ---")
    # question forms read conversation history -> recall
    check("recall: do you remember", route("do you remember oolong"), ToolCall("recall"))
    check("recall: what did we say", route("what did we say last time"), ToolCall("recall"))
    check("recall: we talked about", route("we talked about this before"), ToolCall("recall"))


def test_router_action_tools():
    print("--- router: action tools ---")
    check("dispatch audit", route("dispatch an audit on the docs"), ToolCall("dispatch", {"task": "dispatch an audit on the docs"}, confirmed=False, dry_run=True))
    check("dispatch generic", route("dispatch this to the fleet"), ToolCall("dispatch", {"task": "dispatch this to the fleet"}, confirmed=False, dry_run=True))
    check("start task", route("start a debate on the model"), ToolCall("debate", {"prompt": "start a debate on the model"}, confirmed=False, dry_run=True))
    check("debate keyword", route("debate qwen vs nemotron"), ToolCall("debate", {"prompt": "debate qwen vs nemotron"}, confirmed=False, dry_run=True))


def test_execute_read_tools():
    print("--- execute: read tools ---")
    out = execute(ToolCall("fleet_status"))
    assert "Fleet:" in out or "fleet" in out.lower(), out[:120]
    print("PASS fleet_status ->", out[:90].replace("\n", " | "))
    out = execute(ToolCall("recent_tasks"))
    assert "No recent dost tasks found" in out or "Recent dost tasks" in out, out[:120]
    print("PASS recent_tasks ->", out[:90].replace("\n", " | "))
    out = execute(ToolCall("alerts"))
    assert "alert" in out.lower() or "Alert" in out, out[:120]
    print("PASS alerts ->", out[:90].replace("\n", " | "))


def test_execute_action_unconfirmed():
    print("--- execute: action tools unconfirmed ---")
    out = execute(ToolCall("dispatch", {"task": "run an audit on docs"}, confirmed=False))
    assert "Say \"yes\"" in out, out
    print("PASS dispatch unconfirmed ->", out[:90])
    out = execute(ToolCall("debate", {"prompt": "qwen vs nemotron"}, confirmed=False))
    assert "Say \"yes\"" in out, out
    print("PASS debate unconfirmed ->", out[:90])


def test_resolve_pending():
    print("--- resolve pending ---")
    store_pending("run audit docs", ToolCall("dispatch", {"task": "run audit docs"}, confirmed=False, dry_run=True))
    out = resolve_pending("yes")
    assert out and ("Dispatched" in out or "dispatch" in out.lower()), out
    print("PASS resolve yes ->", out[:90].replace("\n", " | "))
    store_pending("run audit docs", ToolCall("dispatch", {"task": "run audit docs"}, confirmed=False, dry_run=True))
    out = resolve_pending("no")
    assert "Cancelled" in out, out
    print("PASS resolve no ->", out[:90])
    out = resolve_pending("maybe")
    assert out is None, out
    print("PASS resolve maybe -> None")
    # expired offer: a stale "yes" must NOT fire an old dispatch
    store_pending("run audit docs", ToolCall("dispatch", {"task": "run audit docs"}, confirmed=False, dry_run=True))
    import json, time
    with open(jarvis.PENDING_FILE) as f:
        pending = json.load(f)
    pending[-1]["ts"] = time.time() - 400  # older than PENDING_TTL (300s)
    with open(jarvis.PENDING_FILE, "w") as f:
        json.dump(pending, f)
    out = resolve_pending("yes")
    assert out and "expired" in out.lower(), out
    print("PASS resolve expired ->", out[:90])


def test_notify_coalesce_and_dedup():
    print("--- monitor notify: coalesce + dedupe ---")
    # Isolate state in a temp dir so production jarvis_memory/ is untouched.
    tmpdir = Path(tempfile.mkdtemp())
    proactive_monitor.ALERTS_LOG = tmpdir / "alerts.jsonl"
    proactive_monitor.DEDUP_STATE = tmpdir / "alerts_dedup.json"
    proactive_monitor.DEDUP_STATE.write_text("{}")
    proactive_monitor.ALERTS_LOG.write_text("")
    _SENT.clear()

    alerts = [
        {"severity": "critical", "message": f"Pool nvidia_key{k} is down", "metric": f"pool_down_nvidia_key{k}"}
        for k in range(1, 7)
    ]

    # six pool-down alerts -> one iMessage
    sent, present = proactive_monitor.notify(alerts)
    assert sent == 6 and present == 6, (sent, present)
    assert len(_SENT) == 1, f"expected 1 iMessage, got {len(_SENT)}"
    assert "Pool nvidia_key1 is down" in _SENT[0]
    assert "Pool nvidia_key6 is down" in _SENT[0]
    print("PASS coalesce -> 1 iMessage for 6 alerts")

    # second cycle: same metrics -> deduped, silent (0 sent, 6 present)
    _SENT.clear()
    state = {a["metric"]: time.time() - 100 for a in alerts}
    proactive_monitor.DEDUP_STATE.write_text(json.dumps(state))
    sent, present = proactive_monitor.notify(alerts)
    assert sent == 0 and present == 6, (sent, present)
    assert len(_SENT) == 0
    print("PASS dedupe -> 0 sent / 6 present on repeat cycle")

    # degraded: no imsg binary -> 0 sent, history still logged
    _SENT.clear()
    proactive_monitor.DEDUP_STATE.write_text("{}")
    proactive_monitor.ALERTS_LOG.write_text("")
    real = proactive_monitor.IMSG_PATH
    proactive_monitor.IMSG_PATH = "/nonexistent/imsg"
    try:
        sent, present = proactive_monitor.notify(alerts)
        assert sent == 0 and present == 6, (sent, present)
        assert len(_SENT) == 0
        assert proactive_monitor.ALERTS_LOG.exists()
        print("PASS degrade -> 0 sent / 6 present, history logged, no crash")
    finally:
        proactive_monitor.IMSG_PATH = real

    shutil.rmtree(tmpdir)


def test_context_packet():
    print("--- context packet ---")
    ctx = build_cached_context()
    assert isinstance(ctx, str) and len(ctx) > 0, ctx
    print("PASS context packet ->", ctx[:90].replace("\n", " | "))


if __name__ == "__main__":
    test_router_read_tools()
    test_router_negative()
    test_router_remember()
    test_router_action_tools()
    test_execute_read_tools()
    test_execute_action_unconfirmed()
    test_resolve_pending()
    test_notify_coalesce_and_dedup()
    test_context_packet()
    print()
    if FAILS:
        print("FAILURES:", FAILS)
        sys.exit(1)
    print("All jarvis self-tests passed.")
