import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

OLD = '''    if isinstance(sessions, dict):
        items = sessions.values()
    elif isinstance(sessions, list):
        items = sessions
    else:
        return {}'''

NEW = '''    # sessions.json is {"sessions": [...]}, so the records live one level
    # under a wrapper key. Reading the top-level values directly hands the
    # function a list where it expects dicts, and every agent then looks like
    # it has no session at all, which is a fleet-wide false alarm rather than
    # an obvious crash.
    items = None
    if isinstance(sessions, dict):
        for key in ("sessions", "records", "items"):
            if isinstance(sessions.get(key), list):
                items = sessions[key]
                break
        if items is None:
            items = [v for v in sessions.values() if isinstance(v, dict)]
    elif isinstance(sessions, list):
        items = sessions
    else:
        return {}
    if not isinstance(items, list):
        items = []'''

assert s.count(OLD) == 1, "anchor count = %d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  fixed the sessions.json wrapper-key parsing")
