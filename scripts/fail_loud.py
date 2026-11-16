import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

# A delivery that silently no-ops is the failure that matters for this script:
# the rollup would look like it is reporting, and nothing would arrive. So the
# hour is computed, and a failed send is raised rather than logged and dropped.
OLD = '''    if not args.no_deliver:
        d = deliver(r, args.target)
        if d and d.get("delivered"):
            print("  delivered to %s as %s" % (d["to"], d["message_id"]))
        else:
            # Loud, not silent. The rollup exists either way, but a summary
            # that never reached an agent is a summary nobody is reading.
            print("  NOT delivered: %s" % ((d or {}).get("error", "no target")))
    return 0'''

NEW = '''    if not args.no_deliver:
        d = deliver(r, args.target)
        if d and d.get("delivered"):
            print("  delivered to %s as %s" % (d["to"], d["message_id"]))
        else:
            err = (d or {}).get("error", "no target")
            print("  NOT delivered: %s" % err, file=sys.stderr)
            # Non-zero so launchd records the failed run. A summary that
            # computes and then silently fails to arrive is the one failure
            # mode this whole script exists to prevent, so it must not look
            # like a clean run in the log.
            return 1
    return 0'''
assert s.count(OLD) == 1
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  failed delivery now exits non-zero")
