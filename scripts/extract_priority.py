import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

TESTS = '''

def test_degraded_verdict_is_a_system_priority():
    rollup.llm_success_rate = lambda: {"rate": 25, "exit": 1}
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)}]},
    )
    r = rollup.build(NOW)
    assert rollup.priority_for(r) == 15, "a 25% LLM success rate was not escalated"


def test_clean_verdict_is_a_background_priority():
    rollup.llm_success_rate = lambda: {"rate": 95, "exit": 0}
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)}]},
    )
    r = rollup.build(NOW)
    assert rollup.priority_for(r) == 5, "a healthy rollup shouted over a real event"


def test_a_stale_floor_escalates_even_with_a_healthy_llm():
    rollup.llm_success_rate = lambda: {"rate": 99, "exit": 0}
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(-3600)}]},
    )
    r = rollup.build(NOW)
    assert rollup.priority_for(r) == 15, "a dead floor did not escalate"


def test_priority_is_a_number_not_a_string():
    """message.js sorts with `b.priority - a.priority`. A string priority makes
    that NaN, which silently breaks ordering for every message in the inbox."""
    rollup.llm_success_rate = lambda: {"rate": 25, "exit": 1}
    use_fixtures(
        {"agents": {"a1": {"floor": "f1"}}},
        {"sessions": [{"agent_id": "a1", "last_heartbeat": iso(0)}]},
    )
    p = rollup.priority_for(rollup.build(NOW))
    assert isinstance(p, int), "priority must be numeric, got %r" % (p,)
'''

HELPER = '''
def priority_for(r):
    """Numeric inbox priority for a rollup, matching message.js PRIORITY_MAP."""
    tot = r.get("totals") or {}
    rate = (r.get("llm_success_rate") or {}).get("rate")
    attention = tot.get("stale") or tot.get("unknown_heartbeat")
    if attention or (rate is not None and rate < 70):
        return PRIORITY_SYSTEM
    return PRIORITY_BACKGROUND


'''

# Extract the decision so it is testable without a transport round-trip.
anchor = "def deliver(r, target=None):"
assert s.count(anchor) == 1
s = s.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

# deliver() should call it rather than repeat the rule.
OLD = '''    # Severity follows the verdict, so an all-green rollup cannot be mistaken
    # for an incident by whatever reads the inbox.
    tot = r.get("totals") or {}
    rate = (r.get("llm_success_rate") or {}).get("rate")
    attention = tot.get("stale") or tot.get("unknown_heartbeat")
    level = PRIORITY_SYSTEM
    if not attention and rate is not None and rate >= 70:
        level = PRIORITY_BACKGROUND
'''
NEW = '''    # Severity follows the verdict, so an all-green rollup cannot be mistaken
    # for an incident by whatever reads the inbox.
    level = priority_for(r)
'''
assert s.count(OLD) == 1
s = s.replace(OLD, NEW, 1)

p.write_text(s, encoding="utf-8")
print("  extracted priority_for()")
