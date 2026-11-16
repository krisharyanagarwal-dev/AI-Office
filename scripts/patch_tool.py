import pathlib

p = pathlib.Path("scripts/rolling_restart_agents.py")
s = p.read_text(encoding="utf-8")

# 1. Make the fix ref an argument instead of a hardcoded f0d7912, and default to
#    the atomic-write fix that the fleet actually needs to load now.
old_fix = '''def fix_commit():
    try:
        out = subprocess.check_output(
            ["git", "-C", HIVE, "log", "-1", "--format=%H %ct", "f0d7912"],
            text=True).strip()
        h, ts = out.split()
        return h, int(ts)
    except Exception:
        return "f0d7912", 0'''
new_fix = '''FIX_REF = "17669a9"  # atomic write + refuse-to-clobber; default target


def fix_commit(ref=None):
    ref = ref or FIX_REF
    try:
        out = subprocess.check_output(
            ["git", "-C", HIVE, "log", "-1", "--format=%H %ct", ref],
            text=True).strip()
        h, ts = out.split()
        return h, int(ts)
    except Exception:
        return ref, 0'''
assert s.count(old_fix) == 1
s = s.replace(old_fix, new_fix, 1)

# 2. Optional explicit opt-in for the normally protected agents. They are in the
#    registry, not archived, and both have live supervisors that restart on
#    death, so they are inside the same bounded contract; but the default stays
#    protected so an ordinary run can never touch them.
old_args = '''    ap.add_argument("--timeout", type=int, default=90, help="seconds to wait for respawn")
    args = ap.parse_args()'''
new_args = '''    ap.add_argument("--timeout", type=int, default=90, help="seconds to wait for respawn")
    ap.add_argument("--fix", default=FIX_REF, help="commit that must end up loaded")
    ap.add_argument("--include-protected", action="store_true",
                    help="allow restarting mainbot/office-manager; both are in the "
                         "registry and have live supervisors, but they are excluded "
                         "by default")
    args = ap.parse_args()'''
assert s.count(old_args) == 1
s = s.replace(old_args, new_args, 1)

s = s.replace("    commit, commit_ts = fix_commit()",
              "    commit, commit_ts = fix_commit(args.fix)", 1)

old_targets = "def targets(only):\n    pids = agent_pids()\n    order = []\n    for aid in sorted(pids):\n        if aid in NEVER_TOUCH:\n            continue"
new_targets = ("def targets(only, include_protected=False):\n    pids = agent_pids()\n"
               "    held_back = set() if include_protected else NEVER_TOUCH\n    order = []\n"
               "    for aid in sorted(pids):\n        if aid in held_back:\n            continue")
assert s.count(old_targets) == 1
s = s.replace(old_targets, new_targets, 1)

s = s.replace("    order = [a for a in targets(only) if a in todo]",
              "    order = [a for a in targets(only, args.include_protected) if a in todo]", 1)

# Report must reflect the opt-in, otherwise the summary is a lie.
old_held = '''    held = sorted(a for a in stale if a in NEVER_TOUCH)'''
new_held = '''    held = [] if args.include_protected else sorted(a for a in stale if a in NEVER_TOUCH)'''
assert s.count(old_held) == 1
s = s.replace(old_held, new_held, 1)

old_hdr = '''    print("  never touched   : %s" % ", ".join(sorted(NEVER_TOUCH)))'''
new_hdr = '''    print("  never touched   : %s" % (", ".join(sorted(NEVER_TOUCH)) if not args.include_protected
                                      else "(none - --include-protected)"))'''
assert s.count(old_hdr) == 1
s = s.replace(old_hdr, new_hdr, 1)

p.write_text(s, encoding="utf-8")
print("  tool updated: --fix, --include-protected, reporting follows the opt-in")
