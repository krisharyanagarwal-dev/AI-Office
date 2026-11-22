"""
Office audit - read-only fact gathering about the office ITSELF.

Every other probe looks outward (the mini, the laptop's jobs, the repos). Nothing
looked at the office's own wiring, so two defects sat in config/office.json
unnoticed: six department leads with no tier (silently answered by the weakest
pool) and departments citing survey sources that no collector produces any more.

  registry()  agents in config vs tiers vs persona prompt files on disk
  wiring()    each department's leads and sources vs what actually exists
  pools()     provider pools and the fallback chain vs keys PRESENT (never read)
  cadence()   autopilot round files and round lifecycle events vs the interval

Rules (same as sources.py / ops_probes.py):
  * Read-only. Nothing is started, written, deleted or sent anywhere.
  * Never raise: failures come back as data.
  * Secrets are never read into the result: only presence/absence is reported.
  * Unknown is not ok. A missing file is a fact, not a pass.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HOME = Path.home()
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "office.json"
AGENT_DIR = HOME / ".config" / "opencode" / "agent"
ROUNDS_DIR = HOME / "office-os" / "logs" / "autopilot"
EVENTS_PATH = HOME / "office-os" / "logs" / "events.jsonl"
AP_STATE_PATH = HOME / "office-os" / "config" / "autopilot_state.json"
ENV_FILE = HOME / ".env"

# A persona shorter than this is a stub: autopilot would send almost no role.
MIN_PERSONA_BYTES = 200

_CACHE = {"mtime": None, "data": None}


def _config():
    """Parse config/office.json, cached on mtime. Returns (cfg, error_or_None)."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError as e:
        return None, f"config unreadable: {type(e).__name__}"
    if _CACHE["mtime"] != mtime:
        try:
            _CACHE["data"] = json.loads(CONFIG_PATH.read_text())
            _CACHE["mtime"] = mtime
        except (OSError, json.JSONDecodeError) as e:
            return None, f"config unparseable: {type(e).__name__}: {str(e)[:120]}"
    return _CACHE["data"], None


def _collector_names():
    """Survey source names the office can actually produce, from sources.COLLECTORS."""
    try:
        try:
            from core import sources
        except ImportError:
            import sources
        return sorted(fn.__name__.replace("_", "-") for fn in sources.COLLECTORS)
    except Exception as e:  # a broken sources module is itself the finding
        return [f"__error__:{type(e).__name__}"]


def _key_names():
    """pool -> env var name, taken from the client so the two can never drift."""
    try:
        try:
            from core.provider_client import ProviderClient
        except ImportError:
            from provider_client import ProviderClient
        return dict(ProviderClient.KEY_NAMES)
    except Exception:
        return {}


def _env_file_names():
    """Variable NAMES assigned a non-empty value in ~/.env. Values are never kept."""
    names = set()
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            name, _, value = line.partition("=")
            if value.strip().strip("'\""):
                names.add(name.strip())
            else:
                names.discard(name.strip())  # a later empty assignment blanks it
    except OSError:
        pass
    return names


# ---------- registry: agents, tiers, personas ----------
def registry() -> dict:
    cfg, err = _config()
    if err:
        return {"error": err}
    tiers = cfg.get("agent_tiers") or {}
    tier_of = {}
    for tier, ids in tiers.items():
        for a in ids or []:
            tier_of.setdefault(a, []).append(tier)
    leads = {}
    for dept in cfg.get("departments") or []:
        for a in dept.get("leads") or []:
            leads.setdefault(a, []).append(dept.get("id"))

    try:
        on_disk = {p.stem: p for p in AGENT_DIR.glob("*.md")}
        agent_dir_ok = True
    except OSError:
        on_disk, agent_dir_ok = {}, False

    agents = {}
    for a in sorted(set(tier_of) | set(leads)):
        path = on_disk.get(a)
        agents[a] = {
            "tiers": tier_of.get(a, []),
            "leads_of": leads.get(a, []),
            "persona_bytes": (path.stat().st_size if path else 0),
        }
    return {
        "agent_dir_ok": agent_dir_ok,
        "agent_dir": str(AGENT_DIR),
        "agents": agents,
        "untiered_leads": sorted(a for a, v in agents.items() if v["leads_of"] and not v["tiers"]),
        "multi_tiered": sorted(a for a, v in agents.items() if len(v["tiers"]) > 1),
        "no_persona": sorted(a for a, v in agents.items() if v["persona_bytes"] == 0),
        "stub_persona": sorted(
            a for a, v in agents.items() if 0 < v["persona_bytes"] < MIN_PERSONA_BYTES
        ),
        "unassigned_agents": sorted(a for a, v in agents.items() if not v["leads_of"]),
    }


# ---------- wiring: departments vs collectors ----------
def wiring() -> dict:
    cfg, err = _config()
    if err:
        return {"error": err}
    live = set(_collector_names())
    depts = []
    for dept in cfg.get("departments") or []:
        cited = list(dept.get("sources") or [])
        # "dashboard-hub:/api/trading" names collector dashboard-hub plus a path.
        unknown = [s for s in cited if s.split(":", 1)[0] not in live]
        depts.append({
            "id": dept.get("id"),
            "leads": list(dept.get("leads") or []),
            "sources": cited,
            "unknown_sources": unknown,
            "blind": len(unknown) == len(cited) and bool(cited),
            "no_guardrails": not (dept.get("guardrails") or []),
        })
    used = {s.split(":", 1)[0] for d in depts for s in d["sources"]}
    return {
        "live_collectors": sorted(live),
        "departments": depts,
        "unread_collectors": sorted(live - used),
    }


# ---------- pools: config vs keys present ----------
def pools() -> dict:
    cfg, err = _config()
    if err:
        return {"error": err}
    configured = cfg.get("provider_pools") or {}
    key_names = _key_names()
    env_names = _env_file_names()
    out = {}
    for name, pool in configured.items():
        key = key_names.get(name)
        out[name] = {
            "tier": pool.get("tier"),
            "models": len(pool.get("models") or []),
            "key_name": key,
            "key_known": key is not None,
            "key_present": bool(key and (os.environ.get(key) or key in env_names)),
        }
    chain = list(cfg.get("fallback_chain") or [])
    return {
        "pools": out,
        "fallback_chain": chain,
        "unknown_in_chain": [p for p in chain if p not in configured],
        "keyless_pools": sorted(n for n, v in out.items() if not v["key_present"]),
        "pools_off_chain": sorted(n for n in configured if n not in chain),
        "tiers_served": sorted({
            t
            for n, v in out.items() if v["key_present"]
            for t in ([v["tier"]] if isinstance(v["tier"], str) else (v["tier"] or []))
        }),
    }


# ---------- cadence: did the autopilot actually run? ----------
def _round_events():
    """Autopilot round outcomes for the CURRENT orchestrator process.

    A round that starts and neither finishes nor fails is a HANG, invisible in the
    round files alone. But events.jsonl is append-only, so judging lifetime totals
    would keep reporting a hang that a restart has already fixed. The log also
    records orchestrator_started, so the honest window is the rounds started since
    the last one: that is the behaviour of the code running right now.
    """
    counts = {"started": 0, "finished": 0, "failed": 0}
    outcome, order = {}, []          # this process only
    try:
        for line in EVENTS_PATH.read_text().splitlines():
            if "orchestrator_started" not in line and "autopilot_round" not in line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            event, rnd = doc.get("event", ""), doc.get("round")
            if event == "orchestrator_started":
                outcome, order = {}, []   # new process: previous rounds are history
                continue
            for key in counts:
                if event == f"autopilot_round_{key}":
                    counts[key] += 1
                    if not rnd:
                        continue
                    if key == "started":
                        if rnd not in outcome:
                            outcome[rnd] = None
                            order.append(rnd)
                    else:
                        outcome[rnd] = key
    except OSError:
        return None

    # The newest round may legitimately still be running; everything before it
    # should have settled one way or the other.
    newest = order[-1] if order else None
    in_flight = newest if newest and outcome.get(newest) is None else None
    settled = [r for r in order if r != in_flight]
    counts.update({
        "this_process": len(order),
        "settled": len(settled),
        "lost": sum(1 for r in settled if outcome.get(r) is None),
        "newest_round": newest,
        "newest_outcome": outcome.get(newest) if newest else None,
        "in_flight": in_flight,
        "in_flight_age_min": _round_id_age_min(in_flight) if in_flight else None,
    })
    return counts


def _round_id_age_min(round_id):
    """Rounds are stamped %Y%m%d-%H%M%S, so the id itself dates an in-flight round."""
    try:
        return round((time.time() - time.mktime(
            time.strptime(round_id, "%Y%m%d-%H%M%S"))) / 60.0, 1)
    except (ValueError, TypeError):
        return None


def cadence() -> dict:
    cfg, err = _config()
    if err:
        return {"error": err}
    ap = cfg.get("autopilot") or {}
    try:
        rounds = sorted(ROUNDS_DIR.glob("round-*.md"))
        dir_exists = True
    except OSError:
        rounds, dir_exists = [], False
    dir_exists = dir_exists and ROUNDS_DIR.is_dir()
    latest_age_min = None
    if rounds:
        try:
            latest_age_min = round((time.time() - max(p.stat().st_mtime for p in rounds)) / 60.0, 1)
        except OSError:
            latest_age_min = None
    # The autopilot stops for the day once it spends max_rounds_per_day, so after
    # that a stale newest round is correct behaviour, not a stall.
    budget = ap.get("max_rounds_per_day")
    try:
        ap_state = json.loads(AP_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        ap_state = {}
    today = time.strftime("%Y-%m-%d")
    rounds_today = ap_state.get("rounds_today") if ap_state.get("day") == today else 0
    return {
        "enabled": bool(ap.get("enabled")),
        "interval_min": ap.get("interval_min"),
        "max_rounds_per_day": budget,
        "rounds_today": rounds_today,
        "budget_spent": bool(budget and (rounds_today or 0) >= budget),
        "summary_stamped": "last_summary_at" in ap_state,
        "events": _round_events(),
        "events_path": str(EVENTS_PATH),
        "rounds_dir": str(ROUNDS_DIR),
        "rounds_dir_exists": dir_exists,
        "round_files": len(rounds),
        "latest_age_min": latest_age_min,
        "departments": len(cfg.get("departments") or []),
    }
