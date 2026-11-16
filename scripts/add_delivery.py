import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

# 1) import + a delivery helper that reuses the real bus instead of writing
#    inbox files by hand, so the message format cannot drift from message.js.
OLD_IMPORT = "import re\nimport subprocess"
NEW_IMPORT = "import re\nimport subprocess"
assert s.count(OLD_IMPORT) == 1

DELIVER = '''
TARGET = os.environ.get("OPENALICE_ROLLUP_TARGET", "god")


def deliver(r, target=None):
    """Hand the digest to an agent through the existing message bus.

    Reuses lib/message.js sendMessage rather than writing inbox files by hand:
    the bus owns message_id generation and inbox/outbox creation, and a
    hand-rolled writer would drift from its format the first time either side
    changed. Delivery is best-effort and never fails the rollup, because a
    summary that exists but was not delivered still beats one that was never
    computed. A transport failure is reported rather than swallowed.
    """
    to = target or TARGET
    if not to:
        return None
    t = r["totals"]
    llm = r.get("llm_success_rate") or {}
    payload = {
        "type": "status_report",
        "from": "floor-rollup",
        "subject": "hourly floor rollup",
        "digest": render(r),
        "totals": t,
        "llm_success_rate": llm.get("rate"),
        "floors_needing_attention": [
            f["floor"] for f in r["floors"]
            if f["stale"] or f["unknown_heartbeat"]
        ],
        "generated_at": r["generated_at"],
    }
    lib = os.path.join(HIVE, "lib", "message.js")
    if not os.path.isfile(lib):
        return {"delivered": False, "error": "lib/message.js not found"}
    js = (
        "const m=require(process.argv[1]);"
        "const p=JSON.parse(process.argv[2]);"
        "process.stdout.write(m.sendMessage(p.to,p.msg,'low'));"
    )
    try:
        out = subprocess.run(
            ["node", "-e", js, lib, json.dumps({"to": to, "msg": payload})],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        return {"delivered": False, "error": str(e)}
    if out.returncode != 0:
        return {"delivered": False, "error": (out.stderr or "").strip()[:200]}
    return {"delivered": True, "to": to, "message_id": out.stdout.strip()}


'''

anchor = "def main():"
assert s.count(anchor) == 1
s = s.replace(anchor, DELIVER.lstrip("\n") + anchor, 1)

# 2) flag + call in main
OLD_ARGS = '''    ap.add_argument("--dry-run", action="store_true", help="print only, write nothing")'''
NEW_ARGS = '''    ap.add_argument("--dry-run", action="store_true", help="print only, write nothing")
    ap.add_argument("--no-deliver", action="store_true",
                    help="write the rollup but do not message the target agent")
    ap.add_argument("--target", default=None, help="recipient agent id (default: god)")'''
assert s.count(OLD_ARGS) == 1
s = s.replace(OLD_ARGS, NEW_ARGS, 1)

OLD_TAIL = '''    if not args.dry_run:
        write_atomic(OUT, r)
        print("\\n  wrote %s" % OUT)
    return 0'''
NEW_TAIL = '''    if args.dry_run:
        return 0

    write_atomic(OUT, r)
    print("\\n  wrote %s" % OUT)

    if not args.no_deliver:
        d = deliver(r, args.target)
        if d and d.get("delivered"):
            print("  delivered to %s as %s" % (d["to"], d["message_id"]))
        else:
            # Loud, not silent. The rollup exists either way, but a summary
            # that never reached an agent is a summary nobody is reading.
            print("  NOT delivered: %s" % ((d or {}).get("error", "no target")))
    return 0'''
assert s.count(OLD_TAIL) == 1
s = s.replace(OLD_TAIL, NEW_TAIL, 1)

p.write_text(s, encoding="utf-8")
print("  delivery wired to lib/message.js sendMessage")
