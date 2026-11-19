"""
Offline self-test for dost/jarvis.py. No network, no real fleet, no model calls.
Runs: python3 dost/jarvis_selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jarvis  # noqa: E402  (needed to stub dispatch below)
from jarvis import route, execute, ToolCall, build_cached_context, resolve_pending, store_pending

# Stub fleet dispatch so this selftest can never write to HIVE_DIR.
# Mimics the unconfirmed path: restates intent, asks for "yes", writes nothing.
def _stub_dispatch(text, confirmed, dry_run):
    if not confirmed and dry_run:
        return 'I\'d dispatch this to the assistant department as "{0}". Say "yes" to confirm.'.format(text[:70])
    return "Stubbed dispatch: {0}".format(text[:50])

jarvis.dispatch = _stub_dispatch

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
    check("plain chat", route("hey how are you"), None)
    check("plain chat 2", route("write me a python script"), None)


def test_router_action_tools():
    print("--- router: action tools ---")
    check("run audit", route("run an audit on the docs"), ToolCall("dispatch", {"task": "run an audit on the docs"}, confirmed=False, dry_run=True))
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


def test_context_packet():
    print("--- context packet ---")
    ctx = build_cached_context()
    assert isinstance(ctx, str) and len(ctx) > 0, ctx
    print("PASS context packet ->", ctx[:90].replace("\n", " | "))


if __name__ == "__main__":
    test_router_read_tools()
    test_router_action_tools()
    test_execute_read_tools()
    test_execute_action_unconfirmed()
    test_resolve_pending()
    test_context_packet()
    print()
    if FAILS:
        print("FAILURES:", FAILS)
        sys.exit(1)
    print("All jarvis self-tests passed.")
