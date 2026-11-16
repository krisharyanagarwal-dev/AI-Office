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

    t = r["totals"]'''
assert s.count(OLD) == 1
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  target validated against registry before send")
