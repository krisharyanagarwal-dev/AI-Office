import pathlib

p = pathlib.Path("scripts/check_stale_cost_writers.py")
s = p.read_text(encoding="utf-8")

old_scan = """def scan():
    out = subprocess.check_output(["ps", "-eo", "pid=,lstart=,args="], text=True)
    writers, unreadable = [], []
    for line in out.splitlines():
        if "node" not in line or not WRITER.search(line):
            continue
        p = line.split()
        if len(p) < 6:
            continue
        pid, lstart = p[0], " ".join(p[1:6])
        m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/([a-z_]+)\\.js", line)
        label = "%s/%s" % (m.group(1), m.group(2)) if m else "lib/llm"
        ts = parse_lstart(lstart)
        if ts is None:
            unreadable.append((label, pid, lstart))
        else:
            writers.append((label, pid, ts))
    return writers, unreadable"""

new_scan = '''def scan():
    """Return (agent_writers, probes, unreadable).

    An agent manager is a real writer: it calls recordCost on every LLM call,
    so a pre-fix one can clobber the shared database. A one-off probe that did
    `node -e "require('./lib/llm/client.js')"` only loaded the module and
    never writes, so it cannot clobber. Conflating the two would bury the one
    process that matters under a dozen harmless leftovers.
    """
    out = subprocess.check_output(["ps", "-eo", "pid=,lstart=,args="], text=True)
    writers, probes, unreadable = [], [], []
    for line in out.splitlines():
        if "node" not in line or not WRITER.search(line):
            continue
        p = line.split()
        if len(p) < 6:
            continue
        pid, lstart = p[0], " ".join(p[1:6])
        m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/([a-z_]+)\\.js", line)
        label = "%s/%s" % (m.group(1), m.group(2)) if m else "probe"
        ts = parse_lstart(lstart)
        if ts is None:
            unreadable.append((label, pid, lstart))
        elif m:
            writers.append((label, pid, ts))
        else:
            probes.append((label, pid, ts))
    return writers, probes, unreadable'''

assert s.count(old_scan) == 1
s = s.replace(old_scan, new_scan, 1)

old_main = s[s.index("def main():"):]
new_main = '''def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hive", default=DEFAULT_HIVE)
    ap.add_argument("--fix", default=DEFAULT_FIX,
                    help="commit that must be loaded; timestamp is read from git")
    args = ap.parse_args()

    try:
        commit, fix = fix_epoch(args.hive, args.fix)
    except Exception as e:
        print("  cannot resolve fix commit %s: %s" % (args.fix, e))
        return 2

    writers, probes, unreadable = scan()
    stale = [w for w in writers if w[2] < fix]
    stale_probes = [w for w in probes if w[2] < fix]

    print("  fix commit         : %s  %s" % (commit[:8],
          datetime.datetime.fromtimestamp(fix).strftime("%Y-%m-%d %H:%M:%S")))
    print("  agent managers     : %d  (%d on/after fix, %d PRE-FIX)"
          % (len(writers), len(writers) - len(stale), len(stale)))
    for label, pid, ts in sorted(stale):
        print("     STALE  %-32s pid=%-7s started %s" % (
            label, pid, datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")))
    print("  module-only probes : %d  (%d pre-fix, cannot clobber)" % (len(probes), len(stale_probes)))
    for label, pid, ts in unreadable:
        print("     UNREADABLE start time, left alone: pid=%s %r" % (pid, lstart if False else ""))

    if stale:
        print()
        print("  RESULT: %d pre-fix agent manager(s) can still clobber costs.json." % len(stale))
        print("  The union snapshot is doing real work and must not be removed.")
        return 1
    print()
    print("  RESULT: no pre-fix cost writer is live; the union snapshot is redundant.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
s = s[:s.index("def main():")] + new_main
p.write_text(s, encoding="utf-8")
print("  patched: real writers separated from module-only probes")
