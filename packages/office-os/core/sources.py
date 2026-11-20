"""
Sources - read-only collectors, one per office system.

Each collector returns a dict:
    {"name": str, "ok": bool, "age_min": float|None, "summary": str, "problems": [str]}

Rules (from the merge plan):
  * Never raise. A failing collector returns ok=False with the reason.
  * Unreachable or stale is NOT ok. Silence is never reported as "0 problems".
  * Read-only. No collector writes, restarts, or calls a model.
  * Local HTTP calls use short timeouts so one dead service cannot stall the poll.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
STALE_MIN = 30  # a collector file older than this is treated as stale


def _http_json(url, timeout=4):
    """GET a JSON endpoint. Returns (data, error_string_or_None)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")), None
    except Exception as e:  # network, HTTP, or JSON error
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def _file_age_min(path):
    try:
        return (time.time() - Path(path).stat().st_mtime) / 60.0
    except OSError:
        return None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text()), None
    except (OSError, json.JSONDecodeError) as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def _result(name, ok, age_min=None, summary="", problems=None):
    return {
        "name": name,
        "ok": bool(ok),
        "age_min": None if age_min is None else round(age_min, 1),
        "summary": summary,
        "problems": problems or [],
    }


# ---------- office-manager (free collector, every 15 min) ----------
def office_manager():
    name = "office-manager"
    path = HOME / "office-manager" / "collect" / "latest.json"
    data, err = _read_json(path)
    if err:
        return _result(name, False, None, "collector file unreadable", [f"no collector output: {err}"])
    data = data or {}
    age = _file_age_min(path)
    problems = []
    if age is None or age > STALE_MIN:
        problems.append(f"collector output is {age:.0f} min old" if age is not None else "collector output missing")
    audit = data.get("audit") or {}
    sev1 = audit.get("sev1")
    if isinstance(sev1, int) and sev1 > 0:
        problems.append(f"fleet audit reports {sev1} sev-1 findings")
    sev2 = audit.get("sev2")
    if isinstance(sev2, int) and sev2 > 0:
        problems.append(f"fleet audit reports {sev2} sev-2 findings")
    mini = (data.get("mini") or {}).get("agents") or {}
    if mini.get("status") not in (None, "OK"):
        problems.append(f"mini office API: {mini.get('status')}")
    sched = data.get("scheduler") or {}
    if sched.get("failed24h"):
        problems.append(f"{sched['failed24h']} scheduled runs failed in 24h")
    summary = f"audit sev1={sev1} sev2={sev2}; mini={mini.get('status', 'n/a')}"
    return _result(name, not problems, age, summary, problems)


# ---------- office-hud (:4752, launchd com.aryan.office-hud-v2) ----------
HUD = "http://127.0.0.1:4752"


def office_hud():
    name = "office-hud"
    health, err = _http_json(HUD + "/api/health")
    if err:
        return _result(name, False, None, "unreachable", [f"/api/health: {err}"])
    health = health or {}
    # The HUD wraps office-core's health: {"office_core": {"status", "checks": [...]}}
    core = health.get("office_core") if isinstance(health, dict) else None
    if isinstance(core, dict):
        health = dict(health, status=core.get("status"))
        down = [c.get("component") for c in core.get("checks", [])
                if isinstance(c, dict) and c.get("status") not in ("healthy", None)]
    else:
        down = []
    agents, aerr = _http_json(HUD + "/api/agents")
    problems = []
    count = None
    if aerr:
        problems.append(f"/api/agents: {aerr}")
    elif isinstance(agents, dict):
        items = agents.get("agents") if isinstance(agents.get("agents"), list) else agents
        count = len(items) if isinstance(items, list) else None
    status = health.get("status") if isinstance(health, dict) else None
    if status and str(status).upper() not in ("OK", "HEALTHY", "UP", "RUNNING"):
        detail = f" ({', '.join(str(d) for d in down)} not healthy)" if down else ""
        problems.append(f"hud health status: {status}{detail}")
    return _result(name, not problems, 0.0, f"health={status} agents={count}", problems)


# ---------- dashboard-hub (:8600) ----------
def dashboard_hub():
    name = "dashboard-hub"
    _, err = _http_json("http://127.0.0.1:8600/api/health")
    if err:
        return _result(name, False, None, "unreachable", [f"/api/health: {err}"])
    problems = []
    watch, werr = _http_json("http://127.0.0.1:8600/api/watchdog")
    down = []
    if werr:
        problems.append(f"/api/watchdog: {werr}")
    elif isinstance(watch, dict):
        for t in watch.get("targets", []):
            if t.get("state") == "down":
                down.append(f"{t.get('name', t.get('port'))} (fails={t.get('fails')}, gave_up={t.get('gave_up')})")
    if down:
        problems.append(f"{len(down)} watchdog targets down: " + "; ".join(down[:6]))
    trading, terr = _http_json("http://127.0.0.1:8600/api/trading")
    if terr:
        problems.append(f"/api/trading: {terr}")
    elif isinstance(trading, dict) and not trading.get("ok", True):
        problems.append("paper trading feed reports not ok")
    triage_age = _file_age_min(HOME / "AI-Office" / "packages" / "dashboard-hub" / "data" / "triage.json")
    return _result(
        name, not problems, triage_age,
        f"watchdog down={len(down)}; paper feed={'ok' if trading and trading.get('ok') else 'n/a'}",
        problems,
    )


# ---------- openalice-fleet (hive files) ----------
def openalice_fleet():
    name = "openalice-fleet"
    hive = HOME / "AI-Office" / "packages" / "_archive" / "openalice-fleet" / "hive"
    summary_path = hive / "task_truth_summary.json"
    data, err = _read_json(summary_path)
    if err:
        return _result(name, False, None, "task truth summary unreadable", [f"{summary_path.name}: {err}"])
    data = data or {}
    age = _file_age_min(summary_path)
    problems = []
    if age is None or age > 24 * 60:
        problems.append(f"task truth summary is {age / 60:.0f} h old" if age is not None else "summary missing")
    unverified = data.get("unverified") or data.get("unverified_completions")
    if isinstance(unverified, int) and unverified > 0:
        problems.append(f"{unverified} completed tasks have no verified evidence")
    return _result(name, not problems, age, f"truth summary keys={len(data)}", problems)


# ---------- laptop launchd fleet ----------
def laptop_jobs():
    name = "laptop-jobs"
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return _result(name, False, None, "launchctl failed", [f"launchctl: {e}"])
    failing, total = [], 0
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2].startswith("com.aryan."):
            continue
        total += 1
        code = parts[1].strip()
        if code not in ("0", "-") and parts[0].strip() in ("-", ""):
            failing.append(f"{parts[2]} exit {code}")
    problems = [f"{len(failing)} jobs not running with a failing exit: " + "; ".join(failing[:8])] if failing else []
    return _result(name, not problems, 0.0, f"{total} com.aryan.* jobs listed", problems)


# ---------- mini (alias only, short timeout) ----------
def mini_office():
    name = "mini-office"
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "a@macmini",
             "tail -c 4000 /tmp/mini-office.log 2>/dev/null; echo; echo __END__"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _result(name, False, None, "mini unreachable", [f"ssh: {type(e).__name__}"])
    if r.returncode != 0:
        return _result(name, False, None, "mini unreachable", [f"ssh exit {r.returncode}: {r.stderr.strip()[:120]}"])
    log = r.stdout
    problems = []
    if "no API key" in log or "JEV failed" in log:
        problems.append("mini log shows JEV failures")
    summary = "log tail read"
    return _result(name, not problems, 0.0, summary, problems)


# ---------- Ops department (facts from core/ops_probes.py; one ssh call per round) ----------
def _probes():
    """Import ops_probes whether sources is loaded as core.sources or plain sources (Dost's audit)."""
    try:
        from core import ops_probes
    except ImportError:
        import ops_probes
    return ops_probes


def _mini():
    return _probes().mini_probe()


def ops_mini_services():
    name = "ops-mini-services"
    m = _mini()
    if "error" in m:
        return _result(name, False, None, "mini unreachable", [m["error"]])
    down = [f"{k}={v}" for k, v in m.get("services", {}).items() if v != 200]
    sick = [k for k, v in (m.get("router_backends") or {}).items() if v is not True]
    problems = []
    if down:
        problems.append("services not answering: " + ", ".join(down))
    if sick:
        problems.append("model-router backends unhealthy: " + ", ".join(sick))
    disk = m.get("disk_free_gb")
    if isinstance(disk, (int, float)) and disk < 15:
        problems.append(f"mini disk low: {disk} GB free")
    return _result(name, not problems, 0.0,
                   f"{sum(1 for v in m.get('services', {}).values() if v == 200)}/{len(m.get('services', {}))} services up; "
                   f"disk {disk} GB free; via {m.get('route')}", problems)


def ops_mini_jobs():
    name = "ops-mini-jobs"
    m = _mini()
    if "error" in m:
        return _result(name, False, None, "mini unreachable", [m["error"]])
    j = m.get("jobs", {})
    failing = j.get("failing", [])
    kinds = {}
    for f in failing:
        kinds.setdefault(f["kind"], []).append(f["label"].replace("com.aryan.", "").replace("com.user.", "u."))
    problems = [f"{len(v)} {k}: " + ", ".join(v[:8]) for k, v in sorted(kinds.items())]
    return _result(name, not failing, 0.0,
                   f"{j.get('running')} running / {j.get('total')} jobs; {len(failing)} failing", problems)


def ops_paper_safety():
    """PAPER-only invariant. Any doubt is a problem (fail closed)."""
    name = "ops-paper-safety"
    m = _mini()
    if "error" in m:
        return _result(name, False, None, "cannot verify (mini unreachable)", [m["error"]])
    s = m.get("paper_safety", {})
    problems = []
    if s.get("trader_killswitch") != "LOCKED":
        problems.append(f"trader kill switch is {s.get('trader_killswitch')!r}, expected 'LOCKED'")
    if s.get("bot_sandbox") is not True:
        problems.append(f"trading-bot sandbox is {s.get('bot_sandbox')!r}, expected True")
    if s.get("bot_exchange_keys_present") is not False:
        problems.append(f"exchange keys present: {s.get('bot_exchange_keys_present')!r} (must be False)")
    return _result(name, not problems, 0.0,
                   f"killswitch={s.get('trader_killswitch')} sandbox={s.get('bot_sandbox')} "
                   f"keys={s.get('bot_exchange_keys_present')} fleet_paused={s.get('fleet_paused')}", problems)


def ops_market_data():
    name = "ops-market-data"
    m = _mini()
    if "error" in m:
        return _result(name, False, None, "mini unreachable", [m["error"]])
    md = m.get("market_data", {})
    problems = []
    if md.get("data-api.binance.vision") != 200:
        problems.append(f"Binance public data mirror not reachable from mini: {md.get('data-api.binance.vision')}")
    note = "main API blocked on this network (expected; jobs use the mirror)" if md.get("api.binance.com") != 200 else "main API reachable"
    return _result(name, not problems, 0.0, note, problems)


def ops_repo_safety():
    name = "ops-repo-safety"
    try:
        repos = _probes().repo_probe()
    except Exception as e:
        return _result(name, False, None, "repo probe crashed", [str(e)[:160]])
    problems = []
    for repo, info in repos.items():
        if info.get("secret_like_in_staged"):
            problems.append(f"{repo}: secret-like string in STAGED changes - do not commit")
        if info.get("index_lock_age_min", 0) > 10:
            problems.append(f"{repo}: git index.lock is {info['index_lock_age_min']} min old (possibly stale)")
        if repo == "~" and info.get("home_lock_intact") is False:
            problems.append("home-folder repo no longer ignores: " + ", ".join(info.get("unignored_sensitive_paths", [])))
        if (info.get("unpushed_commits") or 0) > 0:
            problems.append(f"{repo}: {info['unpushed_commits']} unpushed commit(s) on {info.get('branch')}")
    return _result(name, not problems, 0.0, f"{len(repos)} repos checked", problems)


COLLECTORS = [
    office_hud,
    laptop_jobs,
    mini_office,
    ops_mini_services,
    ops_mini_jobs,
    ops_paper_safety,
    ops_market_data,
    ops_repo_safety,
]
# Not polled any more (kept above in case they come back):
#   office_manager  - packages/office-manager moved to _archive; its collect job is retired.
#   dashboard_hub   - its launchd jobs were retired; nothing serves :8600.
#   openalice_fleet - moved to _archive; its truth summary is no longer refreshed.


def collect_all():
    """Run every collector. A crash inside one becomes that system's ok=False result."""
    out = []
    for fn in COLLECTORS:
        try:
            out.append(fn())
        except Exception as e:
            out.append(_result(fn.__name__, False, None, "collector crashed", [str(e)[:160]]))
    return out
