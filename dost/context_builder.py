#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Context Builder

Gathers live state from across the company and compresses it into a
≤4K token context string for the LLM. All data is deterministic code —
no LLM derivation. Numbers are injected verbatim; the LLM only narrates.

Modules:
  - hypothesis queue status + gate/holdout results
  + monthly public record
  - calibration ledger
  - fleet health (from running dispatcher)
  - portfolio, performance, fleet agents (from unified-api read-only endpoints)
  - provider health
  - dost memory + recent conversation history

Output: a context string injected into the LLM system prompt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_DIR = (Path.home() / "Documents" / "indian-paper-trading")
QUEUE_DIR = RESEARCH_DIR / "results" / "hypothesis_queue"
CALIBRATION_FILE = RESEARCH_DIR / "results" / "calibration_ledger.json"
PUBLIC_DIR = RESEARCH_DIR / "results" / "public_record"
DOST_DIR = (Path(__file__).resolve().parents[1] / "dost")
DOST_MEMORY = DOST_DIR / "memory.json"
DOST_HISTORY = DOST_DIR / "history.jsonl"
DISPATCHER = (Path.home() / ".openclaw" / "jev-dispatcher.py")
PNL_FILE = (Path.home() / ".openclaw" / "office_pnl.json")

MAX_TOKENS = 4000  # rough cap for the context block

UNIFIED_API_BASE = os.environ.get("DOST_UNIFIED_API_URL", "http://127.0.0.1:4749")
UNIFIED_API_TIMEOUT = 4


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " ..."


def _fetch_unified(path: str) -> Any:
    """Fetch a JSON payload from the read-only unified-api.

    Returns None on any failure so the caller can degrade gracefully —
    the LLM works with stale-or-missing data rather than fabricating it.
    """
    try:
        with urllib.request.urlopen(UNIFIED_API_BASE + path, timeout=UNIFIED_API_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _money(value: Any) -> str:
    """Format a money value as ₹ with 2 decimals, or 'n/a' when missing."""
    try:
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def hypothesis_section() -> str:
    """Summarize hypothesis queue: count by status, latest gate results."""
    lines = ["RESEARCH HYPOTHESIS QUEUE:"]
    if not QUEUE_DIR.exists():
        lines.append("  No hypothesis queue directory.")
        return "\n".join(lines)

    hyps = []
    for p in sorted(QUEUE_DIR.glob("*.json")):
        try:
            hyps.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue

    status_counts: dict[str, int] = {}
    for h in hyps:
        s = h.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    lines.append(f"  Total hypotheses: {len(hyps)}")
    lines.append("  By status: " + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items())))

    # Latest gate/holdout detail for each failed/passed hypothesis
    for h in hyps[-5:]:  # only most recent 5 to stay within token budget
        hid = h.get("id", "?")
        status = h.get("status", "unknown")
        gate = h.get("gate_result") or {}
        holdout = h.get("holdout_result") or {}
        claim = _truncate(h.get("hypothesis", ""), 90)
        line = f"  - {hid} [{status}] {claim}"
        if gate:
            net = gate.get("total_net_pnl")
            n = gate.get("num_trades")
            reason = gate.get("reason", "")
            line += f" | trades={n} net_pnl={net} | gate: {reason}"
        if holdout:
            hnet = holdout.get("holdout_net_pnl")
            hdd = holdout.get("holdout_dd_pct")
            confirmed = holdout.get("confirmed")
            line += f" | holdout: net={hnet} dd={hdd}% confirmed={confirmed}"
        lines.append(line)

    return "\n".join(lines)


def calibration_section() -> str:
    """Summarize calibration ledger: predicted vs realized edge."""
    lines = ["CALIBRATION LEDGER:"]
    cal = _load_json(CALIBRATION_FILE, [])
    if not isinstance(cal, list) or not cal:
        lines.append("  No calibration records yet.")
        return "\n".join(lines)

    lines.append(f"  Records: {len(cal)}")
    well = sum(1 for c in cal if c.get("well_calibrated"))
    lines.append(f"  Well-calibrated: {well}/{len(cal)} ({round(well/len(cal)*100, 1)}%)")

    # Most recent 3
    for c in cal[-3:]:
        hid = c.get("hypothesis_id", "?")
        pred = c.get("predicted_edge_pct")
        real = c.get("realized_edge_pct")
        err = c.get("calibration_error_pct")
        well_cal = c.get("well_calibrated")
        lines.append(f"  - {hid}: predicted={pred}% realized={real}% error={err}% well_calibrated={well_cal}")
    return "\n".join(lines)


def monthly_report_section() -> str:
    """Summarize the latest monthly public report."""
    lines = ["MONTHLY PUBLIC RECORD:"]
    if not PUBLIC_DIR.exists():
        lines.append("  No public record directory.")
        return "\n".join(lines)

    reports = sorted(PUBLIC_DIR.glob("monthly_report_*.json"))
    if not reports:
        lines.append("  No monthly reports yet.")
        return "\n".join(lines)

    latest = json.loads(reports[-1].read_text())
    month = latest.get("month", "?")
    hyp = latest.get("hypotheses", {})
    lines.append(f"  Latest month: {month}")
    lines.append(f"  Total hypotheses: {hyp.get('total', 0)}")
    lines.append(f"  Passed: {latest.get('passed_count', 0)} | Failed: {hyp.get('failed_count', 0)}")
    by_status = hyp.get("by_status", {})
    if by_status:
        lines.append("  By status: " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    cal = latest.get("calibration", {})
    if cal:
        lines.append(f"  Calibration: {cal.get('well_calibrated', 0)}/{cal.get('n', 0)} well-calibrated")
    return "\n".join(lines)


def fleet_section() -> str:
    """Summarize fleet health from the running dispatcher via live metrics."""
    lines = ["FLEET STATUS:"]
    try:
        with urllib.request.urlopen("http://127.0.0.1:8083/metrics", timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        jev = data.get("jev", {})
        pools = data.get("provider_pools", {})
        available = sum(1 for p in pools.values() if p.get("available"))
        total = len(pools)
        pid_file = (Path.home() / ".openclaw" / "jev-dispatcher.pid")
        pid = pid_file.read_text().strip() if pid_file.exists() else "?"
        er = jev.get("error_rate")
        er_total = jev.get("error_rate_total")
        if isinstance(er, (int, float)) and isinstance(er_total, (int, float)):
            error_text = f"error rate {er:.1f}% in the last 24h (all-time {er_total:.1f}%)"
        else:
            error_text = "error rate unavailable"
        lines.append(
            f"  Dispatcher: running (PID {pid}) | {jev.get('tasks_done',0)}/{jev.get('tasks_created',0)} tasks done "
            f"({jev.get('completion_rate',0):.0f}%) | {error_text} "
            f"| {jev.get('calls_today',0)} calls today | {available}/{total} pools available "
            f"| {data.get('free_ceiling',{}).get('headroom_pct',0):.0f}% free-tier headroom"
        )
    except Exception as e:
        lines.append(f"  Dispatcher: unreachable ({e})")
        pid_file = (Path.home() / ".openclaw" / "jev-dispatcher.pid")
        pid = pid_file.read_text().strip() if pid_file.exists() else "?"
        lines.append(f"  PID file: {pid}")

    # Autonomy tier counts (hardcoded from dispatcher knowledge, stable)
    lines.append("  Autonomy tiers: A=13 (autonomous), B=12 (gated), C=7 (human-only)")
    lines.append("  Kill switch: LOCKED | live_orders_allowed: false")
    return "\n".join(lines)


def portfolio_section() -> str:
    """Summarize the live paper portfolio snapshot from unified-api."""
    lines = ["PORTFOLIO (paper trading):"]
    data = _fetch_unified("/api/portfolio")
    if not data:
        lines.append("  Unified API portfolio: unreachable.")
        return "\n".join(lines)
    if not data.get("available"):
        lines.append("  Portfolio data unavailable.")
        return "\n".join(lines)
    lines.append(
        f"  Broker: {data.get('broker', '?')} | Currency: {data.get('currency', 'INR')}"
    )
    lines.append(
        f"  Cash: {_money(data.get('cash'))} | Market value: {_money(data.get('marketValue'))}"
    )
    lines.append(
        f"  Equity: {_money(data.get('equity'))} | Total PnL: {_money(data.get('totalPnl'))} "
        f"(realized {_money(data.get('realizedPnl'))}, unrealized {_money(data.get('unrealizedPnl'))})"
    )
    dd = data.get("drawdownPercent")
    try:
        dd_pct = float(dd) * 100
        lines.append(f"  Drawdown: {dd_pct:.2f}% | Peak equity: {_money(data.get('peakEquity'))}")
    except (TypeError, ValueError):
        lines.append(f"  Drawdown: n/a | Peak equity: {_money(data.get('peakEquity'))}")
    positions = data.get("positions") or []
    lines.append(f"  Positions: {len(positions)}")
    for pos in positions[:8]:
        sym = pos.get("symbol", "?")
        side = pos.get("side", "?")
        qty = pos.get("quantity")
        entry = pos.get("avgEntryPrice")
        notional = pos.get("notional")
        lines.append(
            f"  - {sym} {side} qty={qty} entry={_money(entry)} notional={_money(notional)} "
            f"unrealized={_money(pos.get('unrealizedPnl'))}"
        )
    lines.append(
        f"  As of: {data.get('asOf', '?')} | age: {data.get('ageMinutes', '?')} min | "
        f"stale: {data.get('stale', '?')}"
    )
    return "\n".join(lines)


def performance_section() -> str:
    """Summarize live performance runs from unified-api."""
    lines = ["PERFORMANCE:"]
    data = _fetch_unified("/api/performance")
    if not data:
        lines.append("  Unified API performance: unreachable.")
        return "\n".join(lines)
    if not data.get("available"):
        lines.append("  Performance data unavailable.")
        return "\n".join(lines)
    lines.append(
        f"  Latest equity: {_money(data.get('latestEquity'))} | "
        f"Best: {_money(data.get('bestEquity'))} | Worst: {_money(data.get('worstEquity'))}"
    )
    runs = data.get("runs") or []
    lines.append(f"  Runs: {len(runs)}")
    for run in runs[-5:]:
        rid = run.get("runId", "?")
        status = run.get("status", "?")
        equity = _money(run.get("equity"))
        pnl = _money(run.get("totalPnl"))
        filled = run.get("filledOrders", 0)
        rejected = run.get("rejectedOrders", 0)
        paper = run.get("paperOnly", "?")
        lines.append(
            f"  - {rid} [{status}] equity={equity} pnl={pnl} filled={filled} "
            f"rejected={rejected} paper_only={paper}"
        )
    return "\n".join(lines)


def unified_fleet_section() -> str:
    """Summarize live fleet agents from unified-api."""
    lines = ["FLEET AGENTS (unified-api):"]
    data = _fetch_unified("/api/fleet")
    if not data:
        lines.append("  Unified API fleet: unreachable.")
        return "\n".join(lines)
    agents = data.get("agents") or []
    sessions = data.get("sessions") or []
    terminals = data.get("terminals") or []
    busy = sum(1 for a in agents if str(a.get("status", "")).lower() == "busy")
    healthy = sum(1 for a in agents if str(a.get("status", "")).lower() == "healthy")
    lines.append(
        f"  Agents: {len(agents)} ({busy} busy, {healthy} healthy) | "
        f"Sessions: {len(sessions)} | Terminals: {len(terminals)}"
    )
    for a in agents[:6]:
        lines.append(
            f"  - {a.get('id', '?')} {a.get('name', '?')} [{a.get('role', '?')}] "
            f"{a.get('status', '?')} | {a.get('activity', '?')} | "
            f"last active {a.get('lastActiveSecAgo', '?')}s ago"
        )
    if len(agents) > 6:
        lines.append(f"  ... and {len(agents) - 6} more agents")
    return "\n".join(lines)


def provider_section() -> str:
    """Summarize provider health."""
    lines = ["PROVIDER HEALTH:"]
    # Read from openai_components fallback list
    sys.path.insert(0, str(DOST_DIR))
    try:
        from openai_components import provider_health
        health = provider_health()
        lines.append(f"  OpenAI key configured: {health.get('openai_chat', False)}")
        fbs = health.get("fallbacks_available", [])
        lines.append(f"  Fallback providers available: {', '.join(fbs) if fbs else 'none'}")
    except Exception as e:
        lines.append(f"  Provider health check error: {e}")
    return "\n".join(lines)


def memory_section() -> str:
    """Summarize dost memory + recent conversation history."""
    lines = ["DOST MEMORY & RECENT CONTEXT:"]
    profile = _load_json(DOST_MEMORY, {})
    if profile:
        name = profile.get("name", "?")
        capital = profile.get("capital_inr", 0)
        risk = profile.get("risk_tolerance", "?")
        interests = profile.get("research_interests", [])
        lines.append(f"  User: {name} | Capital: ₹{capital:,} | Risk: {risk}")
        lines.append(f"  Research interests: {', '.join(interests) if interests else 'none'}")
        boundaries = profile.get("boundaries", {})
        lines.append(f"  Boundaries: paper_only={boundaries.get('paper_only', '?')}, "
                     f"kill_switch_locked={boundaries.get('kill_switch_locked', '?')}")

    # Last 3 conversation turns
    lines.append("  Recent conversation:")
    try:
        turns = []
        with open(DOST_HISTORY) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        for t in turns[-3:]:
            user = _truncate(t.get("user", ""), 80)
            dept = t.get("department", "?")
            lines.append(f"    - [{dept}] {user}")
    except FileNotFoundError:
        lines.append("    No conversation history yet.")
    return "\n".join(lines)


def alerts_section() -> str:
    """Summarize recent open alerts from the proactive monitor's JSONL log.

    Reads jarvis_memory/alerts.jsonl and surfaces unique alerts from the
    last 24 hours, deduped by metric so a repeating failure shows once.
    """
    lines = ["RECENT ALERTS:"]
    alerts_log = (Path(__file__).resolve().parents[1] / "dost" / "jarvis_memory" / "alerts.jsonl")
    if not alerts_log.exists():
        lines.append("  No alerts recorded.")
        return "\n".join(lines)

    try:
        with open(alerts_log) as f:
            entries = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        lines.append("  Could not read alerts log.")
        return "\n".join(lines)

    if not entries:
        lines.append("  No alerts recorded.")
        return "\n".join(lines)

    # Last 24 hours, deduped by metric (most recent per metric wins)
    now = time.time()
    day_ago = now - 86400
    seen_metrics = {}
    for e in reversed(entries):
        ts = e.get("ts", 0)
        if ts < day_ago:
            continue
        metric = e.get("metric", "unknown")
        if metric not in seen_metrics:
            seen_metrics[metric] = e

    if not seen_metrics:
        lines.append("  No alerts in the last 24 hours.")
        return "\n".join(lines)

    for metric, e in list(seen_metrics.items())[:8]:
        sev = e.get("severity", "unknown").upper()
        msg = e.get("message", "Unknown alert")
        lines.append(f"  [{sev}] {msg}")

    return "\n".join(lines)


def build_context() -> str:
    """Build the full context string injected into the LLM system prompt."""
    sections = [
        hypothesis_section(),
        "",
        calibration_section(),
        "",
        monthly_report_section(),
        "",
        fleet_section(),
        "",
        portfolio_section(),
        "",
        performance_section(),
        "",
        unified_fleet_section(),
        "",
        provider_section(),
        "",
        alerts_section(),
        "",
        memory_section(),
    ]
    context = "\n".join(sections)
    # Rough token cap: 4 chars ≈ 1 token, so 4000 tokens ≈ 16000 chars
    if len(context) > 16000:
        context = context[:16000] + "\n... [context truncated]"
    return context


if __name__ == "__main__":
    print(build_context())
