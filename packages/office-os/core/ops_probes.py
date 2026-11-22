"""
Ops probes - read-only fact gathering for the office's Ops department.

These are the checks done by hand on 2026-11-17..20 (laptop + Mac mini), turned
into code so the Ops agents see real facts every survey round:

  mini_probe()   ONE ssh call to the mini -> model services, failing launchd jobs
                 (classified), paper-safety facts, market-data reachability.
  repo_probe()   laptop git hygiene: home-folder repo lock, stale index locks,
                 unpushed commits, secret-looking strings in staged files.

Rules (same as sources.py):
  * Read-only. Nothing is started, stopped, moved, deleted or sent anywhere.
  * Never raise: failures come back as data.
  * Secrets are never read into the result: only presence/absence is reported.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

HOME = Path.home()

# --- Mac mini -----------------------------------------------------------------
# Tailscale alias first; LAN fallback (Tailscale has dropped more than once).
MINI_ROUTES = [
    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "a@macmini"],
    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
     "-i", str(HOME / ".ssh" / "id_ed25519_github"),
     "-o", "HostKeyAlias=[100.125.24.105]:2222", "-p", "2222", "a@as-mac-mini-71.local"],
]

# Runs ON the mini with /usr/bin/python3 (3.9, stdlib + yaml). Prints one JSON object.
MINI_SCRIPT = r'''
import json, os, plistlib, subprocess, time, urllib.request
H = os.path.expanduser("~")
out = {}

def http(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except Exception as e:
        return getattr(e, "code", None) or type(e).__name__

out["services"] = {name: http("http://127.0.0.1:%d%s" % (port, path)) for name, port, path in [
    ("ollama-shim", 11434, "/api/tags"), ("mlx", 11435, "/v1/models"),
    ("nvidia-key-manager", 4200, "/v1/models"), ("model-router", 8081, "/health"),
    ("free-harness", 8080, "/health"), ("mini-dost", 8787, "/"),
    ("laptop-dost-link", 18787, "/"), ("openclaw", 18789, "/")]}
try:
    with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=5) as r:
        out["router_backends"] = {k: v.get("healthy") for k, v in json.load(r).get("backends", {}).items()}
except Exception as e:
    out["router_backends"] = {"error": type(e).__name__}

out["market_data"] = {
    "api.binance.com": http("https://api.binance.com/api/v3/ping", 6),
    "data-api.binance.vision": http("https://data-api.binance.vision/api/v3/ping", 6)}

# failing jobs, classified
st = {}
for line in subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout.splitlines()[1:]:
    p = line.split("\t")
    if len(p) == 3 and (p[2].startswith("com.aryan.") or p[2].startswith("com.user.")):
        st[p[2]] = (p[0], p[1])
failing = []
for label, (pid, code) in sorted(st.items()):
    if pid != "-" or code == "0":
        continue
    item = {"label": label, "exit": code, "kind": "runtime"}
    try:
        pl = plistlib.load(open(os.path.join(H, "Library/LaunchAgents/%s.plist" % label), "rb"))
        args = pl.get("ProgramArguments") or []
        miss = [a for a in args if isinstance(a, str) and a.startswith("/") and not os.path.exists(a)]
        wd = pl.get("WorkingDirectory")
        if wd and not os.path.isdir(wd):
            miss.append(wd)
        if miss:
            item.update(kind="missing-path", path=miss[0])
        elif code == "78":
            item["kind"] = "config-or-log-path"
    except Exception:
        item["kind"] = "plist-unreadable"
    failing.append(item)
out["jobs"] = {"total": len(st), "running": sum(1 for v in st.values() if v[0] != "-"), "failing": failing}

# paper safety: presence/absence only, never values
safety = {}
ks = os.path.join(H, "trading/openalice-fleet/state/trader_killswitch_status.json")
try:
    d = json.load(open(ks))
    safety["trader_killswitch"] = d.get("verdict")
    safety["killswitch_checked_at"] = d.get("ts")
except Exception as e:
    safety["trader_killswitch"] = "UNREADABLE: " + type(e).__name__
try:
    import yaml
    c = yaml.safe_load(open(os.path.join(H, "trading/openalice-fleet/trading/trading-bot/config.yaml"))) or {}
    ex = c.get("exchange") or {}
    safety["bot_sandbox"] = ex.get("sandbox")
    safety["bot_exchange_keys_present"] = any(
        str(ex.get(k) or "").strip() and "${" not in str(ex.get(k)) for k in ("apiKey", "api_key", "secret", "api_secret"))
except Exception as e:
    safety["bot_sandbox"] = "UNREADABLE: " + type(e).__name__
safety["fleet_paused"] = any(n.startswith("disable-local-fleet") for n in os.listdir(os.path.join(H, ".config/openalice-fleet")))
out["paper_safety"] = safety

# paper book: the live paper-trading state the trading departments reason from.
# Numbers only - no keys, no credentials, no order paths.
book = {}
SD = os.path.join(H, "trading/openalice-fleet/state")
def _load(name):
    try:
        return json.load(open(os.path.join(SD, name))), None
    except Exception as e:
        return None, type(e).__name__ + ": " + str(e)[:80]
d, err = _load("alphainsider_paper.json")
if d is None:
    book["book_error"] = err
else:
    book["status"] = d.get("status")
    book["open_positions"] = len(d.get("positions") or [])
    book["closed_trades"] = len(d.get("closed") or [])
    book["realized_pnl"] = d.get("realized_pnl")
    book["last_run"] = d.get("last_run")
    book["last_error"] = d.get("last_error")
    book["mark_price"] = d.get("price")
d, err = _load("alphainsider_multistrat.json")
if d is None:
    book["multistrat_error"] = err
else:
    book["mode"] = d.get("mode")
    book["execution_enabled"] = d.get("execution_enabled")
    book["live_trading"] = d.get("live_trading")
    book["multistrat_status"] = d.get("status")
    book["multistrat_error_text"] = (d.get("last_error") or "")[:200]
    book["daily_realized"] = d.get("daily_realized")
d, err = _load("alphainsider_state.json")
if d is None:
    book["poller_error"] = err
else:
    book["poller_status"] = d.get("status")
    # a provider error names a missing VARIABLE, never a value
    book["poller_provider_error"] = (d.get("provider_error") or "")[:120]
    book["new_signals"] = d.get("new_signals")
try:
    hp = os.path.join(SD, "paper_history.jsonl")
    lines = open(hp).read().strip().split("\n")
    book["history_rows"] = len(lines)
    first = json.loads(lines[0]) if lines and lines[0] else {}
    last = json.loads(lines[-1]) if lines and lines[-1] else {}
    book["history_first_ts"] = first.get("ts")
    book["history_last_ts"] = last.get("ts")
    book["history_any_trade"] = any(
        (json.loads(l).get("closed") or 0) > 0 for l in lines if l.strip())
    book["history_age_min"] = round((time.time() - os.path.getmtime(hp)) / 60.0, 1)
except Exception as e:
    book["history_error"] = type(e).__name__ + ": " + str(e)[:80]
out["paper_book"] = book

st2 = os.statvfs(H)
out["disk_free_gb"] = round(st2.f_bavail * st2.f_frsize / 1e9, 1)
print(json.dumps(out))
'''

_CACHE = {"at": 0.0, "data": None}


def mini_probe(max_age_s: int = 120) -> dict:
    """Run MINI_SCRIPT on the mini once; reuse the result for max_age_s."""
    if _CACHE["data"] is not None and time.time() - _CACHE["at"] < max_age_s:
        return _CACHE["data"]
    last_err = "no route tried"
    for route in MINI_ROUTES:
        try:
            r = subprocess.run(route + ["/usr/bin/python3", "-"], input=MINI_SCRIPT,
                               capture_output=True, text=True, timeout=45)
        except (OSError, subprocess.TimeoutExpired) as e:
            last_err = f"{route[-1]}: {type(e).__name__}"
            continue
        if r.returncode == 0 and r.stdout.strip():
            try:
                data = json.loads(r.stdout.strip().splitlines()[-1])
                data["route"] = route[-1]
                _CACHE.update(at=time.time(), data=data)
                return data
            except json.JSONDecodeError:
                last_err = f"{route[-1]}: bad JSON"
        else:
            last_err = f"{route[-1]}: exit {r.returncode} {r.stderr.strip()[:80]}"
    data = {"error": f"mini unreachable ({last_err})"}
    _CACHE.update(at=time.time(), data=data)
    return data


# --- Laptop repos ---------------------------------------------------------------
REPOS = [HOME / "AI-Office", HOME / "AI-Office" / "src" / "openalice-fleet", HOME]
SECRET_RE = re.compile(r"(nvapi-[A-Za-z0-9_-]{20}|gsk_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{20}"
                       r"|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY)")
MUST_BE_IGNORED = [".env", ".ssh/id_ed25519_github", ".secrets-backup", "Documents/polymarket/.env"]


def _git(repo, *args, timeout=15):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout


def repo_probe() -> dict:
    out = {}
    for repo in REPOS:
        name = "~" if repo == HOME else str(repo).replace(str(HOME), "~")
        info = {}
        if not (repo / ".git").exists():
            out[name] = {"present": False}
            continue
        try:
            lock = repo / ".git" / "index.lock"
            if lock.exists():
                age = (time.time() - lock.stat().st_mtime) / 60
                info["index_lock_age_min"] = round(age, 1)
            _, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            info["branch"] = branch.strip()
            code, ahead = _git(repo, "rev-list", "--count", "@{u}..HEAD")
            info["unpushed_commits"] = int(ahead.strip()) if code == 0 and ahead.strip().isdigit() else None
            _, staged = _git(repo, "diff", "--cached", "--name-only")
            staged_files = [f for f in staged.splitlines() if f]
            info["staged_files"] = len(staged_files)
            _, diff = _git(repo, "diff", "--cached", timeout=30)
            info["secret_like_in_staged"] = bool(SECRET_RE.search(diff))
            if repo == HOME:
                ignored = {}
                for p in MUST_BE_IGNORED:
                    rc = subprocess.run(["git", "-C", str(HOME), "check-ignore", "-q", p]).returncode
                    ignored[p] = rc == 0
                info["home_lock_intact"] = all(ignored.values())
                info["unignored_sensitive_paths"] = [p for p, ok in ignored.items() if not ok]
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {str(e)[:100]}"
        out[name] = info
    return out
