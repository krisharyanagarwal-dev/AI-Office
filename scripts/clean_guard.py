import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

MESSY = '''    # Validate against the registry before sending. lib/message.js
    # ensureInboxOutbox will happily mkdir an inbox for an agent that does not
    # exist, so a typo does not fail, it fabricates a phantom agent directory
    # and reports a successful delivery to nobody. Checking first turns a
    # silent data-corruption bug into a loud error.
    known = floor_of(read_json(REGISTRY, {}) or {})
    if "god" in (read_json(REGISTRY, {}) or {}).get("agents", {}) or known:
        registered = set(known) | {"god"}
    else:
        registered = set()
    reg = read_json(REGISTRY, {}) or {}
    agents = reg.get("agents")
    if isinstance(agents, dict):
        registered = set(agents)
    elif isinstance(agents, list):
        registered = {a.get("id") for a in agents if isinstance(a, dict)}
    if to not in registered:
        return {"delivered": False,
                "error": "target %r is not a registered agent" % to}
'''

CLEAN = '''    # Validate against the registry before sending. lib/message.js
    # ensureInboxOutbox will happily mkdir an inbox for an agent that does not
    # exist, so a typo does not fail loudly, it fabricates a phantom agent
    # directory and reports a successful delivery to nobody. Checking first
    # turns silent data corruption into a visible error.
    if to not in registered_agents():
        return {"delivered": False,
                "error": "target %r is not a registered agent" % to}
'''
assert s.count(MESSY) == 1
s = s.replace(MESSY, CLEAN, 1)

HELPER = '''
def registered_agents():
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
s = s.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

p.write_text(s, encoding="utf-8")
print("  cleaned: single registered_agents() helper")
