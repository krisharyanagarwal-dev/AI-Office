import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

OLD = '''    hb = parse_ts(session.get("last_heartbeat"))
    if hb is None:
        return None  # unknown, not stale. Do not invent a verdict.
    age = (now - hb).total_seconds()
    return age'''

NEW = '''    hb = parse_ts(session.get("last_heartbeat"))
    if hb is None:
        return None  # unknown, not stale. Do not invent a verdict.
    # `now` arrives as an epoch float, hb as an aware datetime, so comparing
    # them directly raises rather than reporting. Convert the heartbeat to an
    # epoch instead of the clock to a datetime, so --now stays a plain number.
    try:
        return now - hb.timestamp()
    except (OverflowError, OSError, ValueError):
        return None'''

assert s.count(OLD) == 1, "anchor count = %d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  fixed the epoch/datetime comparison in staleness()")
