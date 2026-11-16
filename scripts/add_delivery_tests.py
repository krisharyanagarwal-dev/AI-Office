import pathlib

p = pathlib.Path("tests/test_rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

TESTS = '''

def test_a_phantom_target_is_refused_before_anything_is_created():
    """lib/message.js mkdirs an inbox for any id you hand it, so sending to a
    typo would invent an agent and report success. The guard has to run first,
    and the refusal has to be a return, not an exception, so main can report
    it as a failed delivery."""
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)}]},
    )
    r = rollup.build(NOW)
    d = rollup.deliver(r, "no-such-agent-xyz")
    assert d is not None and d.get("delivered") is False
    assert "not a registered agent" in d.get("error", "")


def test_a_registered_target_passes_the_guard():
    rollup.llm_success_rate = lambda: None
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)}]},
    )
    r = rollup.build(NOW)
    # a1 is registered, so the guard must not reject it. It will still fail
    # later on transport in the test environment, which is fine: the point is
    # that the error is NOT the "not a registered agent" one.
    d = rollup.deliver(r, "a1")
    assert d is None or "not a registered agent" not in str(d.get("error", ""))


def test_node_is_resolved_at_runtime_not_pinned():
    """node lives under nvm, whose path carries a version number. Pinning it
    would break the moment nvm upgrades, and a scheduled job that cannot find
    its interpreter looks exactly like a job that found nothing to report."""
    node = rollup.find_node()
    assert node, "no node interpreter could be resolved"
    assert os.access(node, os.X_OK)
    assert re.match(r"^[0-9]", os.path.basename(node)) is None, \\
        "resolved node should be the interpreter binary, not a version dir"
'''

# needs `re` and `os` at test module scope
if "\nimport re\n" not in s:
    s = s.replace("import os\n", "import os\nimport re\n", 1)

p.write_text(s.rstrip("\n") + "\n" + TESTS, encoding="utf-8")
print("  added 3 delivery tests")
