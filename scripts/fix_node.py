import pathlib

p = pathlib.Path("scripts/rollup_floor_summary.py")
s = p.read_text(encoding="utf-8")

OLD = "import re\nimport subprocess"
NEW = "import re\nimport shutil\nimport subprocess"
assert s.count(OLD) == 1
s = s.replace(OLD, NEW, 1)

FIND = '''
def find_node():
    """Locate node without pinning a version.

    launchd gives a job a minimal PATH, so `node` is absent from a scheduled
    run even though the agents find it fine. It lives under nvm, whose path
    carries the version number, so hardcoding the interpreter means the rollup
    breaks silently the next time nvm is upgraded. Resolve at run time instead
    and prefer the newest nvm build, falling back to the usual install paths.
    """
    which = shutil.which("node")
    if which:
        return which
    import glob
    nvm = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
    if nvm:
        return nvm[-1]
    for cand in ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if os.access(cand, os.X_OK):
            return cand
    return None


'''

anchor = "def deliver(r, target=None):"
assert s.count(anchor) == 1
s = s.replace(anchor, FIND.lstrip("\n") + anchor, 1)

OLD_RUN = '''    try:
        out = subprocess.run(
            ["node", "-e", js, lib, json.dumps({"to": to, "msg": payload})],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        return {"delivered": False, "error": str(e)}'''
NEW_RUN = '''    node = find_node()
    if not node:
        return {"delivered": False, "error": "node not found"}
    try:
        out = subprocess.run(
            [node, "-e", js, lib, json.dumps({"to": to, "msg": payload})],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        return {"delivered": False, "error": str(e)}'''
assert s.count(OLD_RUN) == 1
s = s.replace(OLD_RUN, NEW_RUN, 1)

p.write_text(s, encoding="utf-8")
print("  node resolution is now run-time, not a pinned path")
