import pathlib

p = pathlib.Path("scripts/rolling_restart_agents.py")
s = p.read_text(encoding="utf-8")

# A start time we could not parse is UNKNOWN, not old. Treating ts == 0 as
# stale made the script report and target agents whose lstart field it failed
# to read, which would restart a perfectly healthy agent for no reason.
old_targets = """    pids = agent_pids()
    stale = {a: p for a, p in pids.items()
             if p and max(p.values()) < commit_ts}
    live = {a: p for a, p in pids.items() if a not in stale}"""
new_targets = """    pids = agent_pids()
    # A pid whose start time could not be parsed is UNKNOWN, never "old":
    # restarting a healthy agent is the expensive mistake, so unknown means
    # leave it alone and say so.
    def started(p):
        vals = [t for t in p.values() if t]
        return max(vals) if vals else 0

    unknown = {a for a, p in pids.items() if p and not started(p)}
    stale = {a: p for a, p in pids.items()
             if p and started(p) and started(p) < commit_ts}
    live = {a: p for a, p in pids.items() if a not in stale and a not in unknown}"""
assert s.count(old_targets) == 1
s = s.replace(old_targets, new_targets, 1)

old_print = """    print("\\n  agents running old code (need restart): %d" % len(stale))
    print("  agents already on new code            : %d" % len(live))
    if live:
        print("    already new: %s" % ", ".join(sorted(live)[:10]))"""
new_print = """    print("\\n  agents running old code (need restart): %d" % len(stale))
    print("  agents already on new code            : %d" % len(live))
    if unknown:
        print("  start time unparseable, left alone    : %d %s"
              % (len(unknown), sorted(unknown)))
    if live:
        print("    already new: %s" % ", ".join(sorted(live)[:10]))"""
assert s.count(old_print) == 1
s = s.replace(old_print, new_print, 1)

p.write_text(s, encoding="utf-8")
print("  rolling_restart_agents.py: unknown start time no longer counts as stale")
