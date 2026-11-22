#!/usr/bin/env python3
"""office-core worker: import integrity check for the dost package.

Catches the class of breakage the 2026-11-20 subpackage refactor caused and
that an agent loop can re-introduce at any commit:

  STALE_FLAT    a module moved into a subpackage is still imported flat
                (`from workspace import ...` after workspace.py moved to
                dost/collab/), which only fails at runtime.
  STALE_DOTTED  `dost.<module>` still points at a pre-move path
                (`from dost.audit_log import ...` -> dost.ops.audit_log).
  PATH_DEPTH    a module inside a subpackage still computes DOST_DIR as
                `parent` or COMPANY_DIR as `parent.parent`, so its data and
                sys.path land one level too deep. This is the silent one: it
                forks runtime state into dost/<subpkg>/jarvis_memory/ where
                no reader looks.
  IMPORT_FAIL   the module does not import as dost.<pkg>.<mod> at all.

Report only. It never edits a file, never commits, never touches launchd.
Writes a JSON verdict the office HUD and the orchestrator can read, and
exits non-zero when anything is broken so a launchd job's last-exit-code
shows red.

Stdlib only. No network, no keys, no model calls -- runs at zero metered
cost, which is the point: this is the check that should not need Claude.

Usage:
    python3 import_integrity.py              # check, write report, exit 0/1
    python3 import_integrity.py --quiet      # report only, no stdout detail
    python3 import_integrity.py --no-write   # do not write the report file
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

AI_OFFICE = Path(__file__).resolve().parent.parent.parent.parent
DOST = AI_OFFICE / "dost"
REPORT = Path.home() / ".openclaw" / "import_integrity.json"

# Subpackages created by the refactor. A module living in one of these is
# reachable as dost.<pkg>.<mod>, never as a bare top-level name.
SUBPACKAGES = ("bots", "collab", "memory_pkg", "ops", "security", "trading", "voice", "billing")

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "tests", ".qoder"}

# A module inside a subpackage is one level deeper than it used to be, so
# these expressions now resolve one directory too deep.
BAD_DOST_DIR = re.compile(r"DOST_DIR\s*=\s*Path\(__file__\)\.resolve\(\)\.parent\s*$")
BAD_COMPANY_DIR = re.compile(r"COMPANY_DIR\s*=\s*Path\(__file__\)\.resolve\(\)\.parent\.parent\s*$")
BAD_SYSPATH = re.compile(r"sys\.path\.insert\(\s*0\s*,\s*str\(Path\(__file__\)\.resolve\(\)\.parent\)\s*\)")
BAD_STATE_DIR = re.compile(r"Path\(__file__\)\.resolve\(\)\.parent\s*/\s*[\"']jarvis_memory[\"']")


def module_map() -> dict:
    """Map every module name that lives in a subpackage to that subpackage."""
    moved = {}
    for pkg in SUBPACKAGES:
        d = DOST / pkg
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            if f.stem != "__init__":
                moved[f.stem] = pkg
    return moved


def root_modules() -> set:
    """Module names still at dost/ root -- a flat import of these is fine."""
    return {f.stem for f in DOST.glob("*.py")}


def python_files() -> list:
    out = []
    for root, dirs, files in os.walk(DOST):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(".py"):
                out.append(Path(root) / fn)
    return sorted(out)


def imported_names(tree: ast.AST) -> list:
    """Top-level name of every import, with its line. `from a.b import c` -> a."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((node.lineno, a.name.split(".")[0], a.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, already package-correct
                continue
            if node.module:
                found.append((node.lineno, node.module.split(".")[0], node.module))
    return found


def scan() -> list:
    """Static scan. Returns a list of finding dicts."""
    moved = module_map()
    roots = root_modules()
    findings = []

    for fp in python_files():
        rel = str(fp.relative_to(AI_OFFICE))
        try:
            src = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append({"kind": "UNREADABLE", "file": rel, "line": 0, "detail": str(exc)})
            continue

        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            findings.append({"kind": "SYNTAX", "file": rel, "line": exc.lineno or 0,
                             "detail": exc.msg})
            continue

        in_subpkg = fp.parent.name in SUBPACKAGES and fp.parent.parent == DOST

        for lineno, head, full in imported_names(tree):
            # A bare name that now lives in a subpackage.
            if head in moved and head not in roots:
                findings.append({
                    "kind": "STALE_FLAT", "file": rel, "line": lineno,
                    "detail": f"{full} -> {moved[head]}.{head}",
                    "fix": f"import it as {moved[head]}.{head} (or dost.{moved[head]}.{head})",
                })
            # dost.<module> where <module> has moved.
            if head == "dost" and full.startswith("dost."):
                second = full.split(".")[1] if full.count(".") >= 1 else ""
                if second in moved and second not in SUBPACKAGES:
                    findings.append({
                        "kind": "STALE_DOTTED", "file": rel, "line": lineno,
                        "detail": f"{full} -> dost.{moved[second]}.{second}",
                        "fix": f"use dost.{moved[second]}.{second}",
                    })

        if in_subpkg:
            for i, line in enumerate(src.splitlines(), 1):
                # Match code only. These files carry comments that quote the
                # bad expression to explain the bug it caused, and a scanner
                # that flags its own documentation is a scanner nobody trusts.
                stripped = line.split("#", 1)[0].rstrip()
                if not stripped:
                    continue
                if BAD_DOST_DIR.search(stripped):
                    findings.append({"kind": "PATH_DEPTH", "file": rel, "line": i,
                                     "detail": "DOST_DIR = parent (one level too deep)",
                                     "fix": "parent.parent -- the package root"})
                elif BAD_COMPANY_DIR.search(stripped):
                    findings.append({"kind": "PATH_DEPTH", "file": rel, "line": i,
                                     "detail": "COMPANY_DIR = parent.parent (one level too deep)",
                                     "fix": "parent.parent.parent"})
                elif BAD_SYSPATH.search(stripped):
                    findings.append({"kind": "PATH_DEPTH", "file": rel, "line": i,
                                     "detail": "sys.path gets the subpackage dir, not dost/",
                                     "fix": "insert parent.parent so siblings resolve"})
                elif BAD_STATE_DIR.search(stripped):
                    findings.append({"kind": "PATH_DEPTH", "file": rel, "line": i,
                                     "detail": "jarvis_memory under the subpackage forks runtime state",
                                     "fix": "anchor it at parent.parent / 'jarvis_memory'"})

    return findings


def import_check() -> list:
    """Import every subpackage module in a child process.

    A child keeps a half-imported module or a module that starts a thread from
    poisoning this process, and a hang cannot wedge the launchd job.
    """
    moved = module_map()
    mods = [f"dost.{pkg}.{name}" for name, pkg in sorted(moved.items(), key=lambda kv: (kv[1], kv[0]))]
    if not mods:
        return []

    code = (
        "import importlib, json, sys\n"
        "sys.path.insert(0, %r)\n"
        "bad = []\n"
        "for m in %r:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "    except BaseException as e:\n"
        "        bad.append([m, type(e).__name__, str(e)[:200]])\n"
        "print(json.dumps(bad))\n"
    ) % (str(AI_OFFICE), mods)

    try:
        res = subprocess.run([sys.executable, "-I", "-c", code],
                             capture_output=True, text=True, timeout=240, cwd=str(AI_OFFICE))
    except subprocess.TimeoutExpired:
        return [{"kind": "IMPORT_FAIL", "file": "dost/", "line": 0,
                 "detail": "import sweep timed out after 240s", "fix": "a module blocks at import time"}]

    line = (res.stdout or "").strip().splitlines()
    if not line:
        return [{"kind": "IMPORT_FAIL", "file": "dost/", "line": 0,
                 "detail": f"sweep produced no result (rc={res.returncode}): {(res.stderr or '')[-200:]}",
                 "fix": "run the sweep by hand"}]
    try:
        bad = json.loads(line[-1])
    except ValueError:
        return [{"kind": "IMPORT_FAIL", "file": "dost/", "line": 0,
                 "detail": "sweep output was not JSON", "fix": "run the sweep by hand"}]

    out = []
    for mod, exc, msg in bad:
        out.append({"kind": "IMPORT_FAIL", "file": mod.replace(".", "/") + ".py", "line": 0,
                    "detail": f"{exc}: {msg}", "fix": "resolve the import above"})
    return out


# Known-benign: these two load correctly as scripts (how launchd runs them) but
# not as dost.voice.*, because dost/dost.py shadows the dost package and
# dost/__init__.py does not re-export every private helper. Tracked, not failed.
KNOWN = {
    ("IMPORT_FAIL", "dost/voice/voice_chat.py"),
    ("IMPORT_FAIL", "dost/voice/voice_cli.py"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    if not DOST.is_dir():
        print(f"import_integrity: no dost/ at {DOST}", file=sys.stderr)
        return 2

    started = time.time()
    findings = scan() + import_check()

    known, live = [], []
    for f in findings:
        (known if (f["kind"], f["file"]) in KNOWN else live).append(f)

    by_kind = {}
    for f in live:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1

    report = {
        "ts": time.time(),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "duration_s": round(time.time() - started, 2),
        "root": str(DOST),
        "modules_in_subpackages": len(module_map()),
        "status": "OK" if not live else "BROKEN",
        "counts": by_kind,
        "findings": live,
        "known_benign": known,
    }

    if not args.no_write:
        try:
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            tmp = REPORT.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(report, indent=2))
            os.replace(tmp, REPORT)  # atomic: a reader never sees a half file
        except OSError as exc:
            print(f"import_integrity: could not write {REPORT}: {exc}", file=sys.stderr)

    if not args.quiet:
        print(f"import_integrity: {report['status']} "
              f"({len(live)} finding(s), {len(known)} known-benign, "
              f"{report['modules_in_subpackages']} modules, {report['duration_s']}s)")
        for f in live:
            print(f"  {f['kind']:13} {f['file']}:{f['line']}  {f['detail']}")
            if f.get("fix"):
                print(f"  {'':13} fix: {f['fix']}")

    return 0 if not live else 1


if __name__ == "__main__":
    sys.exit(main())
