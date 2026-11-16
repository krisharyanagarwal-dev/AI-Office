import pathlib

p = pathlib.Path("scripts/snapshot_costs_union.py")
s = p.read_text(encoding="utf-8")

old = """    union = read_json(UNION)
    before = sum(len((v.get("records") or [])) for v in union.values() if isinstance(v, dict))
    added, grew, repaired = merge_into_union(live, union)
    after = sum(len((v.get("records") or [])) for v in union.values() if isinstance(v, dict))

    write_atomic(UNION, union)

    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s live_ids=%d union_ids=%d union_records=%d added=%s grew=%s repaired=%s\\n" % (
            time.strftime("%Y-%m-%dT%H:%M:%S"), len(live), len(union), after,
            added or "-", grew or "-", repaired or "-"))"""

new = """    union = read_json(UNION)
    before = sum(len((v.get("records") or [])) for v in union.values() if isinstance(v, dict))
    added, grew, repaired = merge_into_union(live, union)
    after = sum(len((v.get("records") or [])) for v in union.values() if isinstance(v, dict))

    # How much history live is missing that the archive is holding. This is the
    # direct measure of clobber damage still being absorbed, and it is the only
    # number that says whether this job is doing real work.
    live_records = sum(len((v.get("records") or [])) for v in live.values() if isinstance(v, dict))
    gap = after - live_records
    behind = sorted(
        k for k in union
        if len(((live.get(k) or {}).get("records")) or []) < len((union[k].get("records") or []))
    )

    write_atomic(UNION, union)

    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s live_ids=%d union_ids=%d live_records=%d union_records=%d gap=%d behind=%d added=%s grew=%s repaired=%s\\n" % (
            time.strftime("%Y-%m-%dT%H:%M:%S"), len(live), len(union), live_records, after, gap,
            len(behind), added or "-", grew or "-", repaired or "-"))"""

assert s.count(old) == 1, "anchor count = %d" % s.count(old)
s = s.replace(old, new, 1)

old_print = """    if added or grew or repaired:
        print("union %d ids / %d records (was %d); added=%s grew=%s repaired=%s"
              % (len(union), after, before, added, grew, repaired))
    else:
        print("union steady at %d ids / %d records" % (len(union), after))"""
new_print = """    if added or grew or repaired or gap:
        print("union %d ids / %d records (was %d); live %d records, gap %d across %d agents; added=%s grew=%s repaired=%s"
              % (len(union), after, before, live_records, gap, len(behind), added, grew, repaired))
    else:
        print("union steady at %d ids / %d records, live keeping pace" % (len(union), after))"""
assert s.count(old_print) == 1
s = s.replace(old_print, new_print, 1)

p.write_text(s, encoding="utf-8")
print("  snapshot now logs the live-vs-archive gap and how many agents are behind")
