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
    health, err = _http_json(HUD + "/health")
    if err:
        return _result(name, False, None, "unreachable", [f"/api/health: {err}"])
    health = health or {}
    # The HUD wraps office-core's health: {"office_core": {"status", "checks": [...]}}
    core = health.get("office_core") if isinstance(health, dict) else None
    if isinstance(core, dict):
        health = dict(health, status=core.get("status"))
        down = [c.get("component") for c in core.get("checks", [])
                if isinstance(c, dict) and c.get("status") not in ("healthy", None, "degraded")]
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


# ---------- office self-audit (facts from core/office_audit.py; local, keyless) ----------
def _audit():
    """Import office_audit whether sources is loaded as core.sources or plain sources."""
    try:
        from core import office_audit
    except ImportError:
        import office_audit
    return office_audit


def office_registry():
    """Agents in config vs their tier vs their persona file on disk."""
    name = "office-registry"
    try:
        r = _audit().registry()
    except Exception as e:
        return _result(name, False, None, "registry probe crashed", [str(e)[:160]])
    if "error" in r:
        return _result(name, False, None, "config unreadable", [r["error"]])
    problems = []
    if not r["agent_dir_ok"]:
        problems.append(f"persona dir unreadable: {r['agent_dir']} - every agent falls back to a generic role")
    leads_no_persona = [a for a in r["no_persona"] if r["agents"][a]["leads_of"]]
    if r["untiered_leads"]:
        problems.append(
            "department leads with no agent_tiers entry (routed to the weakest 'general' pool): "
            + ", ".join(r["untiered_leads"])
        )
    if leads_no_persona:
        problems.append(
            "department leads with no persona file (autopilot sends 'a helpful specialist'): "
            + ", ".join(leads_no_persona)
        )
    if r["stub_persona"]:
        problems.append("persona under 200 bytes (a stub, not a role): " + ", ".join(r["stub_persona"]))
    if r["multi_tiered"]:
        problems.append("agent listed in more than one tier (first match wins silently): "
                        + ", ".join(r["multi_tiered"]))
    summary = (f"{len(r['agents'])} agents; {len(r['no_persona'])} without a persona, "
               f"{len(r['unassigned_agents'])} in no department")
    return _result(name, not problems, 0.0, summary, problems)


def office_wiring():
    """Each department's cited survey sources vs the collectors that actually run."""
    name = "office-wiring"
    try:
        r = _audit().wiring()
    except Exception as e:
        return _result(name, False, None, "wiring probe crashed", [str(e)[:160]])
    if "error" in r:
        return _result(name, False, None, "config unreadable", [r["error"]])
    problems = []
    blind = [d["id"] for d in r["departments"] if d["blind"]]
    if blind:
        problems.append(
            "departments whose every cited source is dead - they answer from no evidence at all: "
            + ", ".join(blind)
        )
    for d in r["departments"]:
        if d["unknown_sources"] and not d["blind"]:
            problems.append(f"{d['id']}: cites dead source(s) " + ", ".join(d["unknown_sources"]))
        if d["no_guardrails"]:
            problems.append(f"{d['id']}: no guardrails listed")
        if not d["leads"]:
            problems.append(f"{d['id']}: no leads, so the autopilot skips it")
    if r["unread_collectors"]:
        problems.append("collectors nothing reads (wasted poll): " + ", ".join(r["unread_collectors"]))
    summary = f"{len(r['departments'])} departments over {len(r['live_collectors'])} live collectors"
    return _result(name, not problems, 0.0, summary, problems)


def office_pools():
    """Provider pools and the fallback chain vs which keys are PRESENT (never read)."""
    name = "office-pools"
    try:
        r = _audit().pools()
    except Exception as e:
        return _result(name, False, None, "pool probe crashed", [str(e)[:160]])
    if "error" in r:
        return _result(name, False, None, "config unreadable", [r["error"]])
    problems = []
    if r["unknown_in_chain"]:
        problems.append("fallback_chain names pools that do not exist: " + ", ".join(r["unknown_in_chain"]))
    unknown_key = sorted(n for n, v in r["pools"].items() if not v["key_known"])
    if unknown_key:
        problems.append("pools with no env var mapped in provider_client: " + ", ".join(unknown_key))
    if r["keyless_pools"]:
        problems.append("pools whose key is absent from the environment and ~/.env: "
                        + ", ".join(r["keyless_pools"]))
    for tier in ("pro", "general", "lite"):
        if tier not in r["tiers_served"]:
            problems.append(f"no keyed pool serves tier '{tier}' - those agents cannot answer")
    summary = (f"{len(r['pools'])} pools, {len(r['pools']) - len(r['keyless_pools'])} keyed; "
               f"chain {' -> '.join(r['fallback_chain']) or 'empty'}")
    return _result(name, not problems, 0.0, summary, problems)


def office_cadence():
    """Did the autopilot actually produce rounds, or is it only configured to?"""
    name = "office-cadence"
    try:
        r = _audit().cadence()
    except Exception as e:
        return _result(name, False, None, "cadence probe crashed", [str(e)[:160]])
    if "error" in r:
        return _result(name, False, None, "config unreadable", [r["error"]])
    interval = r["interval_min"] or 30
    problems = []
    age = r["latest_age_min"]
    if not r["enabled"]:
        summary = "autopilot disabled in config"
        return _result(name, True, age, summary, [])
    ev = r.get("events")
    if ev is None:
        problems.append(f"cannot read the event log at {r['events_path']} - cadence unverifiable")
    elif ev["settled"] and ev["lost"] == ev["settled"]:
        problems.append(
            f"all {ev['settled']} settled rounds of the running orchestrator STARTED and never "
            f"finished or failed - every round blocks mid-round (see {r['events_path']})"
        )
    elif ev["lost"]:
        problems.append(
            f"{ev['lost']} of {ev['settled']} settled rounds in the running orchestrator started "
            "without finishing or failing - rounds are being lost, not completed"
        )
    elif not r["rounds_dir_exists"] or r["round_files"] == 0:
        problems.append(
            f"autopilot is enabled (every {interval} min) but has written no round file to "
            f"{r['rounds_dir']} - enabled is not running"
        )
    if ev and ev["in_flight"] and (ev["in_flight_age_min"] or 0) > 2 * interval:
        problems.append(
            f"round {ev['in_flight']} has been in flight {ev['in_flight_age_min']} min, over "
            f"2x the {interval} min interval - it is stalled, not slow"
        )
    if age is not None and age > 3 * interval and not problems and not r["budget_spent"]:
        problems.append(f"newest round file is {age} min old, over 3x the {interval} min interval")
    ev_bit = (f"; {ev['started']}/{ev['finished']}/{ev['failed']} started/finished/failed all-time, "
              f"this process {ev['this_process']}, last round {ev['newest_outcome'] or 'in flight'}") if ev else ""
    budget_bit = (f"; daily budget SPENT ({r['rounds_today']}/{r['max_rounds_per_day']}), rounds resume tomorrow"
                  if r["budget_spent"] else
                  f"; {r['rounds_today']}/{r['max_rounds_per_day']} rounds used today")
    summary = (f"{r['round_files']} round files; newest {'none' if age is None else str(age) + ' min'} old"
               f"{ev_bit}{budget_bit}")
    return _result(name, not problems, age, summary, problems)


def _iso_age_min(ts):
    """Minutes since an ISO-8601 timestamp, or None if it cannot be read."""
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t).total_seconds() / 60.0, 1)
    except (ValueError, TypeError):
        return None


def paper_book():
    """The live paper-trading book on the mini: positions, closed trades, realized P&L.

    This is the evidence the trading departments were missing. It is deliberately
    blunt about an empty book: a bot that has taken no trades has produced no
    sample, and no claim of edge can rest on it. Reporting 0 P&L as 'ok' is how
    silence gets mistaken for success.
    """
    name = "paper-book"
    m = _mini()
    if "error" in m:
        return _result(name, False, None, "cannot verify (mini unreachable)", [m["error"]])
    b = m.get("paper_book") or {}
    if not b:
        return _result(name, False, None, "mini returned no paper-book facts",
                       ["the mini probe produced no paper_book block - is the state dir present?"])

    problems = []
    # 1. the paper boundary, before anything about performance
    if b.get("execution_enabled") is True:
        problems.append("URGENT: execution_enabled is TRUE in alphainsider_multistrat.json - paper boundary breached")
    if b.get("live_trading") is True:
        problems.append("URGENT: live_trading is TRUE in alphainsider_multistrat.json - paper boundary breached")
    if b.get("mode") not in (None, "paper"):
        problems.append("URGENT: multistrat mode is %r, expected 'paper'" % (b.get("mode"),))

    # 2. unreadable state is not an empty book
    for key, label in (("book_error", "alphainsider_paper.json"),
                       ("multistrat_error", "alphainsider_multistrat.json"),
                       ("poller_error", "alphainsider_state.json"),
                       ("history_error", "paper_history.jsonl")):
        if b.get(key):
            problems.append("%s unreadable: %s" % (label, b[key]))

    # 3. freshness
    age = _iso_age_min(b.get("last_run"))
    if age is not None and age > 60:
        problems.append("book last_run is %s min old - the paper loop is not running" % age)
    hist_age = b.get("history_age_min")
    if hist_age is not None and hist_age > 60:
        problems.append("paper_history.jsonl is %s min old - no new history rows" % hist_age)

    # 4. degraded upstreams, with the reason, since they explain an empty book
    if b.get("poller_status") == "degraded":
        problems.append("signal poller degraded: %s" % (b.get("poller_provider_error") or "no reason given"))
    if b.get("multistrat_status") == "degraded":
        problems.append("multistrat degraded: %s" % (b.get("multistrat_error_text") or "no reason given"))
    if b.get("status") not in (None, "ok"):
        problems.append("paper book status is %r" % (b.get("status"),))

    # 5. the sample itself - an empty book cannot support any claim
    if b.get("history_any_trade") is False:
        problems.append(
            "ZERO closed trades in %s history rows since %s - there is no sample, so no "
            "edge, cost or risk claim can rest on this book"
            % (b.get("history_rows"), (b.get("history_first_ts") or "?")[:10])
        )

    summary = ("open %s, closed %s, realized %s, mark %s, mode %s" % (
        b.get("open_positions"), b.get("closed_trades"), b.get("realized_pnl"),
        b.get("mark_price"), b.get("mode")))
    return _result(name, not problems, age, summary, problems)

COLLECTORS = [
    office_hud,
    laptop_jobs,
    mini_office,
    ops_mini_services,
    ops_mini_jobs,
    ops_paper_safety,
    ops_market_data,
    ops_repo_safety,
    paper_book,
    office_registry,
    office_wiring,
    office_pools,
    office_cadence,
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
