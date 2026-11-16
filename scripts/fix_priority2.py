import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

OLD_JS = '''        "process.stdout.write(m.sendMessage(p.to,p.msg,'low'));"'''
NEW_JS = '''        "process.stdout.write(m.sendMessage(p.to,p.msg,p.priority));"'''
assert s.count(OLD_JS) == 1
s = s.replace(OLD_JS, NEW_JS, 1)

OLD_ARGS = '''            [node, "-e", js, lib, json.dumps({"to": to, "msg": payload})],'''
NEW_ARGS = '''            [node, "-e", js, lib,
             json.dumps({"to": to, "msg": payload, "priority": level})],'''
assert s.count(OLD_ARGS) == 1
s = s.replace(OLD_ARGS, NEW_ARGS, 1)

# Explain the numeric contract next to the sort that depends on it.
OLD_NOTE = '''    js = ('''
NEW_NOTE = '''    # message.js sorts with `b.priority - a.priority`, so priority is a NUMBER.
    # Passing the string 'low' made that arithmetic NaN, which silently broke
    # ordering for every message already sitting in the recipient's inbox.
    js = ('''
assert s.count(OLD_NOTE) == 1
s = s.replace(OLD_NOTE, NEW_NOTE, 1)

OLD_T = 'TARGET = os.environ.get("OPENALICE_ROLLUP_TARGET", "god")'
NEW_T = '''TARGET = os.environ.get("OPENALICE_ROLLUP_TARGET", "god")

# Numeric, matching message.js PRIORITY_MAP. A fleet-wide degraded verdict is
# a SYSTEM event (15); a clean rollup is a background tick (5), so a quiet
# hour does not shout over a real system event.
PRIORITY_SYSTEM = 15
PRIORITY_BACKGROUND = 5'''
assert s.count(OLD_T) == 1
s = s.replace(OLD_T, NEW_T, 1)

OLD_P = '''    to = target or TARGET
    if not to:
        return None
'''
NEW_P = '''    to = target or TARGET
    if not to:
        return None

    # Severity follows the verdict, so an all-green rollup cannot be mistaken
    # for an incident by whatever reads the inbox.
    tot = r.get("totals") or {}
    rate = (r.get("llm_success_rate") or {}).get("rate")
    attention = tot.get("stale") or tot.get("unknown_heartbeat")
    level = PRIORITY_SYSTEM
    if not attention and rate is not None and rate >= 70:
        level = PRIORITY_BACKGROUND
'''
assert s.count(OLD_P) == 1
s = s.replace(OLD_P, NEW_P, 1)

p.write_text(s, encoding="utf-8")
print("  priority numeric + verdict-derived")
