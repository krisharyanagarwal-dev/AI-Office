import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

OLD = '''    to = target or TARGET
    if not to:
        return None
    t = r["totals"]'''

NEW = '''    to = target or TARGET
    if not to:
        return None

    # Validate against the registry before sending. lib/message.js
    # ensureInboxOutbox will happily mkdir an inbox for an agent that does not
    # exist, so a typo does not fail loudly, it fabricates a phantom agent
    # directory and reports a successful delivery to nobody. Checking first
    # turns silent data corruption into a visible error.
    if to not in registered_agents():
        return {"delivered": False,
                "error": "target %r is not a registered agent" % to}

    t = r["totals"]'''
assert s.count(OLD) == 1, "anchor=%d" % s.count(OLD)
s = s.replace(OLD, NEW, 1)

HELPER = '''def registered_agents():
    """Agent ids the registry actually knows about."""
    agents = (read_json(REGISTRY, {}) or {}).get("agents")
    if isinstance(agents, dict):
        return set(agents)
    if isinstance(agents, list):
        return {a.get("id") for a in agents if isinstance(a, dict)}
    return set()


'''
anchor = "def deliver(r, target=None):"
assert s.count(anchor) == 1
s = s.replace(anchor, HELPER + anchor, 1)

# The docstring still claims delivery never fails the rollup. It can now exit
# non-zero, so leave the comment matching the code.
s = s.replace(
    "    changed. Delivery is best-effort and never fails the rollup, because a\n"
    "    summary that exists but was not delivered still beats one that was never\n"
    "    computed. A transport failure is reported rather than swallowed.\n",
    "    changed. The rollup file is written either way, but a failed send exits\n"
    "    non-zero, because a summary that computes and then never arrives is the\n"
    "    one failure mode this script exists to prevent.\n", 1)

p.write_text(s, encoding="utf-8")
print("  guard applied + docstring matched to behaviour")
