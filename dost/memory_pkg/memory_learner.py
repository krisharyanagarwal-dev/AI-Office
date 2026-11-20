#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Memory Learner

Every N interactions, the LLM proposes a JSON patch to the user profile
(interests, preferences, ongoing threads). Deterministic code applies it
against a schema whitelist — the LLM never touches files directly.

"LLM proposes, code disposes" — same discipline as the rest of the dost.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COMPANY_DIR = Path(__file__).resolve().parent.parent.parent
DOST_DIR = Path(__file__).resolve().parent.parent
DOST_MEMORY = DOST_DIR / "memory.json"
DOST_HISTORY = DOST_DIR / "history.jsonl"
sys.path.insert(0, str(DOST_DIR))

from openai_components import chat_completion  # noqa: E402

LEARN_EVERY = 10  # interactions between learning cycles

# Whitelist of profile fields the LLM is allowed to propose.
ALLOWED_FIELDS = {
    "name", "capital_inr", "risk_tolerance", "preferred_markets",
    "goals", "research_interests", "boundaries",
}


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _count_interactions() -> int:
    try:
        with open(DOST_HISTORY) as f:
            return sum(1 for line in f if line.strip())
    except FileNotFoundError:
        return 0


def _propose_patch(recent_history: list[dict], profile: dict) -> dict | None:
    """Ask the LLM for a profile patch. Returns dict or None."""
    history_text = "\n".join(
        f"- {h.get('ts','')[:16]} [{h.get('department','?')}] {h.get('user','')[:100]}"
        for h in recent_history[-20:]
    )
    system = (
        "You are the memory learner for THE CLAUDE COMPANY's dost. "
        "Given recent conversation history + the current user profile, propose "
        "a JSON patch to keep the profile accurate. Only these fields may be "
        "changed: name, capital_inr, risk_tolerance, preferred_markets, goals, "
        "research_interests, boundaries. "
        "Return ONLY valid JSON: {\"patch\": {field: value, ...}, \"reason\": \"...\"} "
        "If nothing needs updating, return {\"patch\": {}, \"reason\": \"no change\"}. "
        "Do not invent fields outside the whitelist. Do not add explanations outside JSON."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Current profile: {json.dumps(profile)}\n\nRecent history:\n{history_text}"},
    ]
    result = chat_completion(messages, temperature=0.3, max_tokens=400)
    text = result.get("text", "").strip()
    try:
        data = json.loads(text)
        return data.get("patch", {})
    except (json.JSONDecodeError, KeyError):
        # Try to extract a JSON object from the text
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group()).get("patch", {})
            except json.JSONDecodeError:
                pass
        return None


def _apply_patch(profile: dict, patch: dict) -> dict:
    """Apply patch strictly against the whitelist. Deterministic — no LLM."""
    updated = dict(profile)
    for key, value in patch.items():
        if key not in ALLOWED_FIELDS:
            continue  # silently drop non-whitelisted fields
        updated[key] = value
    updated["last_learned_at"] = datetime.now(timezone.utc).isoformat()
    return updated


def learn() -> dict:
    """Run one learning cycle. Returns a report dict."""
    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "interactions": _count_interactions(),
        "patch_applied": False,
        "reason": "",
    }

    if _count_interactions() < LEARN_EVERY:
        report["reason"] = f"not enough interactions ({_count_interactions()} < {LEARN_EVERY})"
        return report

    # Load profile + recent history
    MEMORY = None  # avoid circular import; load directly
    profile = _load_json(DOST_MEMORY, {})
    history = []
    try:
        with open(DOST_HISTORY) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        history.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass

    patch = _propose_patch(history, profile)
    if not patch:
        report["reason"] = "LLM proposed no patch"
        return report

    updated = _apply_patch(profile, patch)
    if updated == profile:
        report["reason"] = "patch resulted in no change"
        return report

    DOST_MEMORY.write_text(json.dumps(updated, indent=2))
    report["patch_applied"] = True
    report["reason"] = f"applied patch: {json.dumps(patch)}"
    return report


if __name__ == "__main__":
    print(json.dumps(learn(), indent=2))
