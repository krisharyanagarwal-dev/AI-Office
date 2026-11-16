import pathlib

p = pathlib.Path("scripts/rolling_restart_agents.py")
s = p.read_text(encoding="utf-8")

old = '''    held = [] if args.include_protected else sorted(a for a in stale if a in NEVER_TOUCH)
    todo = {a: p for a, p in stale.items() if a not in NEVER_TOUCH}'''

new = '''    # Both of these must honour --include-protected. Filtering todo by
    # NEVER_TOUCH unconditionally silently dropped mainbot and office-manager
    # even when the operator explicitly asked for them, so the run reported 56
    # while two confirmed pre-fix writers stayed behind.
    excluded = set() if args.include_protected else NEVER_TOUCH
    held = sorted(a for a in stale if a in excluded)
    todo = {a: p for a, p in stale.items() if a not in excluded}'''

assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("  todo now honours --include-protected")
