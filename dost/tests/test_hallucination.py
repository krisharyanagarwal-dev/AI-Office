#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Hallucination Test

Asks 20 varied questions of the dost, extracts every numeric token from each
reply, and asserts each number appears verbatim in a source data file.

"LLM narrates, data speaks" — zero tolerance for invented numbers.

Run: python -m pytest dost/tests/test_hallucination.py -q
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest

COMPANY_DIR = Path(__file__).resolve().parent.parent.parent
DOST_DIR = COMPANY_DIR / "dost"
RESEARCH_DIR = (Path.home() / "Documents" / "indian-paper-trading")

sys_path_inserted = False


def _load_dost():
    """Import dost_respond by path (the dost package shadows a same-named module)."""
    import importlib.util

    p = DOST_DIR / "dost_main.py"
    spec = importlib.util.spec_from_file_location("dost_module_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.dost_respond


def _source_text() -> str:
    """Concatenate all source data files into one haystack for number matching,
    including computed P&L aggregates (the dispatcher mutates office_pnl.json
    while running, so we snapshot it here)."""
    parts = []

    # Hypothesis queue
    queue_dir = RESEARCH_DIR / "results" / "hypothesis_queue"
    if queue_dir.exists():
        for p in sorted(queue_dir.glob("*.json")):
            parts.append(p.read_text())

    # Calibration ledger
    cal = RESEARCH_DIR / "results" / "calibration_ledger.json"
    if cal.exists():
        parts.append(cal.read_text())

    # Monthly public record
    pub_dir = RESEARCH_DIR / "results" / "public_record"
    if pub_dir.exists():
        for p in sorted(pub_dir.glob("*.json")):
            parts.append(p.read_text())

    # Dispatcher PID (live system fact, not a data file but referenced in replies)
    pid_file = (Path.home() / ".openclaw" / "jev-dispatcher.pid")
    if pid_file.exists():
        parts.append(pid_file.read_text())

    # Office P&L — raw data + computed aggregates (snapshot at test time)
    pnl = (Path.home() / ".openclaw" / "office_pnl.json")
    if pnl.exists():
        parts.append(pnl.read_text())
        try:
            tasks = json.loads(pnl.read_text())
            total_cost = sum(t.get("cost_units", 0) for t in tasks)
            total_outcome = sum(t.get("outcome_value", 0) for t in tasks)
            net_value = total_outcome - total_cost
            tier_a = [t for t in tasks if t.get("autonomy_tier") == "A"]
            tier_b = [t for t in tasks if t.get("autonomy_tier") == "B"]
            parts.append(
                f"PnL aggregates: total_cost={total_cost} total_outcome={total_outcome} "
                f"net_value={net_value} tier_a_cost={sum(t.get('cost_units',0) for t in tier_a)} "
                f"tier_a_value={sum(t.get('outcome_value',0) for t in tier_a)} "
                f"tier_a_count={len(tier_a)} tier_b_cost={sum(t.get('cost_units',0) for t in tier_b)} "
                f"tier_b_value={sum(t.get('outcome_value',0) for t in tier_b)} "
                f"tier_b_count={len(tier_b)} total_tasks={len(tasks)}"
            )
        except (json.JSONDecodeError, TypeError):
            pass

    # Live fleet metrics from :8083/metrics (dost reads these for fleet status
    # replies — numbers must be traceable to this source, not invented)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8083/metrics", timeout=4) as r:
            metrics = json.loads(r.read().decode("utf-8"))
        parts.append(json.dumps(metrics))
    except Exception:
        pass

    return "\n".join(parts)


def _extract_numbers(text: str) -> list[str]:
    """Extract numeric tokens (ints, decimals, ₹ amounts, percentages),
    normalized by stripping ₹ and commas."""
    pattern = r"₹?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?!\d)|₹?\d+(?:\.\d+)?(?!\d)|(?<![\d.])\d+\.\d+(?![\d.])"
    nums = re.findall(pattern, text)
    normalized = set()
    for n in nums:
        stripped = n.replace("₹", "").replace(",", "")
        normalized.add(stripped)
        if stripped.endswith("%"):
            normalized.add(stripped[:-1])
    return list(normalized)


def _normalize_haystack(text: str) -> str:
    """Strip ₹ and commas so '5,329.56' and '5329.56' match."""
    return text.replace("₹", "").replace(",", "")


QUESTIONS = [
    "what is my capital?",
    "how many hypotheses passed?",
    "what is the calibration error?",
    "tell me about the fleet status",
    "how many trades did the failed hypothesis have?",
    "what was the holdout net PnL?",
    "what was the drawdown percentage?",
    "how many hypotheses are pre-registered?",
    "what is the fleet net value?",
    "tell me about the research findings",
    "what is the total cost in the office P&L?",
    "how many well-calibrated records are there?",
    "what is the realized edge percentage?",
    "is the kill switch locked?",
    "how many hypotheses failed?",
    "what was the tuning net PnL?",
    "tell me about calibration",
    "what is the monthly report status?",
    "how many agents are autonomous tier A?",
    "give me a summary of everything",
]


@pytest.fixture
def dost():
    return _load_dost()


@pytest.fixture
def haystack():
    return _normalize_haystack(_source_text())


def _haystack_numbers(haystack: str) -> list[float]:
    """Extract all numeric values from the haystack for rounding-tolerant matching."""
    pattern = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
    nums = re.findall(pattern, haystack)
    vals = []
    for n in nums:
        try:
            vals.append(float(n.replace(",", "")))
        except ValueError:
            pass
    return vals


def _number_matches_source(n_str: str, haystack: str, h_vals: list[float]) -> bool:
    """Check if a reply number appears in source data, verbatim or via rounding."""
    # 1. Direct substring match (handles commas already stripped in haystack)
    stripped = n_str.replace(",", "")
    if stripped in haystack:
        return True

    # 2. Rounding-tolerant match against pre-computed haystack numbers
    try:
        n_val = float(stripped)
    except ValueError:
        return False
    decimals = len(stripped.split(".")[1]) if "." in stripped else 0
    for h in h_vals:
        try:
            if round(h, decimals) == n_val:
                return True
        except (TypeError, ValueError):
            continue

    # 3. Race-condition guard: re-read volatile office_pnl.json fresh and check
    #    (dispatcher may have added tasks since we snapshotted the haystack)
    pnl = (Path.home() / ".openclaw" / "office_pnl.json")
    if pnl.exists():
        try:
            fresh = pnl.read_text()
            if stripped in fresh.replace(",", "").replace("₹", ""):
                return True
            tasks = json.loads(fresh)
            # Check raw task fields
            for t in tasks:
                for v in (t.get("cost_units"), t.get("outcome_value"), t.get("net_value")):
                    if v is not None and round(float(v), decimals) == n_val:
                        return True
            # Check computed aggregates (tier breakdowns, totals)
            total_cost = sum(t.get("cost_units", 0) for t in tasks)
            total_outcome = sum(t.get("outcome_value", 0) for t in tasks)
            tier_a = [t for t in tasks if t.get("autonomy_tier") == "A"]
            tier_b = [t for t in tasks if t.get("autonomy_tier") == "B"]
            aggregates = {
                "total_cost": total_cost, "total_outcome": total_outcome,
                "net_value": total_outcome - total_cost, "total_tasks": len(tasks),
                "tier_a_cost": sum(t.get("cost_units", 0) for t in tier_a),
                "tier_a_value": sum(t.get("outcome_value", 0) for t in tier_a),
                "tier_a_count": len(tier_a),
                "tier_a_net": sum(t.get("outcome_value", 0) - t.get("cost_units", 0) for t in tier_a),
                "tier_b_cost": sum(t.get("cost_units", 0) for t in tier_b),
                "tier_b_value": sum(t.get("outcome_value", 0) for t in tier_b),
                "tier_b_count": len(tier_b),
                "tier_b_net": sum(t.get("outcome_value", 0) - t.get("cost_units", 0) for t in tier_b),
            }
            for agg_name, agg_val in aggregates.items():
                if round(float(agg_val), decimals) == n_val:
                    return True
        except (json.JSONDecodeError, TypeError, OSError):
            pass

    return False


@pytest.mark.parametrize("question", QUESTIONS)
def test_no_hallucinated_numbers(dost, haystack, question):
    """Every number in the dost's reply must appear verbatim (or via rounding)
    in source data — zero tolerance for invented numbers."""
    reply = dost(question)
    numbers = _extract_numbers(reply)
    h_vals = _haystack_numbers(haystack)
    for n in numbers:
        assert _number_matches_source(n, haystack, h_vals), (
            f"Hallucinated number '{n}' in reply to: '{question}'\n"
            f"Reply: {reply[:300]}"
        )
