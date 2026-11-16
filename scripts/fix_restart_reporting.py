import pathlib

p = pathlib.Path("scripts/rolling_restart_agents.py")
s = p.read_text(encoding="utf-8")

old = """    print("\\n  agents running old code (need restart): %d" % len(stale))
    print("  agents already on new code            : %d" % len(live))
    if unknown:
        print("  start time unparseable, left alone    : %d %s"
              % (len(unknown), sorted(unknown)))
    if live:
        print("    already new: %s" % ", ".join(sorted(live)[:10]))"""

new = """    # Agents that are old but on the never-touch list are reported honestly
    # rather than folded into the "needs restart" count, so the headline
    # number always matches what the run will actually do.
    held = sorted(a for a in stale if a in NEVER_TOUCH)
    todo = {a: p for a, p in stale.items() if a not in NEVER_TOUCH}

    print("\\n  agents running old code (need restart): %d" % len(todo))
    print("  agents already on new code            : %d" % len(live))
    if held:
        print("  old code but never touched by design : %d %s" % (len(held), held))
    if unknown:
        print("  start time unparseable, left alone    : %d %s"
              % (len(unknown), sorted(unknown)))
    if live:
        print("    already new: %s" % ", ".join(sorted(live)[:10]))"""

assert s.count(old) == 1
s = s.replace(old, new, 1)
s = s.replace('    order = [a for a in targets(only) if a in stale]',
              '    order = [a for a in targets(only) if a in todo]', 1)
p.write_text(s, encoding="utf-8")
print("  headline count now matches what the run will do")
