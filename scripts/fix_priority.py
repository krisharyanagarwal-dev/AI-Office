import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

OLD = '''    js = (
        "const m=require(process.argv[1]);"
        "const p=JSON.parse(process.argv[2]);"
        "process.stdout.write(m.sendMessage(p.to,p.msg,'low'));"
    )'''
NEW = '''    # message.js sorts with `b.priority - a.priority`, so priority is a NUMBER.
    # Passing the string 'low' made that arithmetic NaN, which silently
    # destroyed the ordering for every message already in the recipient inbox.
    # SYSTEM is the honest level for a fleet-wide degraded verdict, and it is
    # the same value the bus uses for a real system event.
    js = (
        "const m=require(process.argv[1]);"
        "const p=JSON.parse(process.argv[2]);"
        "process.stdout.write(m.sendMessage(p.to,p.msg,p.priority));"
    )'''
assert s.count(OLD) == 1
s = s.replace(OLD, NEW, 1)

OLD_ARGS = '''        json.dumps({"to": to, "msg": payload}),'''
NEW_ARGS = '''            json.dumps({"to": to, "msg": payload, "priority": PRIORITY}),'''
assert s.count(OLD_ARGS) == 1
s = s.replace(OLD_ARGS, NEW_ARGS, 1)

OLD_T = 'TARGET = os.environ.get("OPENALICE_ROLLUP_TARGET", "god")'
NEW_T = '''TARGET = os.environ.get("OPENALICE_ROLLUP_TARGET", "god")

# Numeric, matching message.js PRIORITY_MAP. A fleet-wide degraded verdict is
# a SYSTEM event; a clean rollup is a background tick.
PRIORITY_SYSTEM = 15
PRIORITY_BACKGROUND = 5
PRIORITY = int(os.environ.get("OPENALICE_ROLLUP_PRIORITY", PRIORITY_SYSTEM))'''
assert s.count(OLD_T) == 1
s = s.replace(OLD_T, NEW_T, 1)

# Choose the level from the actual verdict, not a constant.
OLD_P = '''    to = target or TARGET
    if not to:
        return None
'''
NEW_P = '''    to = target or TARGET
    if not to:
        return None

    level = PRIORITY_SYSTEM
    t0 = r.get("totals") or {}
    degraded = t0.get("stale") or t0.get("unknown_heartbeat")
    if not degraded and (r.get("llm_success_rate") or {}).get("rate") is not None:
        if (r.get("llm_success_rate") or {}).get("rate") >= 70:
            level = PRIORITY_BACKGROUND
'''
assert s.count(OLD_P) == 1
s = s.replace(OLD_P, NEW_P, 1)

s = s.replace('"priority": PRIORITY}', '"priority": level}', 1)

p.write_text(s, encoding="utf-8")
print("  priority is now numeric and derived from the verdict")
