"""Screener manipulation watch for Dost.

Watches the stock screener output for manipulation/anomaly signals in the
screened universe and triggers Dost fleet self-healing remediation when the
screener pipeline or the screened stocks show distress.

Read-only observation of screener artifacts; self-healing actions (task
re-dispatch, pool failover, service restart) are paper/testnet-only and never
place live orders or touch credentials.

Severity mapping from screener signals to self-healing actions:
- screener pipeline stuck (no fresh artifacts / empty universe) -> check_stuck_tasks
- manipulation signals detected -> check_pool_saturation
- critical manipulation -> run_once (full self-healing cycle)
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `import ops`)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # AI-Office/ (for `from dost...`)

from memory_pkg.unified import get_unified_memory

from ops.self_healing import FleetSelfHealing, HealingAction

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills"))  # dost/skills
try:
    from screener_ev_integration import get_ev_criteria
except ImportError:  # skill not shipped -> degrade gracefully, no EV scoring

    def get_ev_criteria(symbol: str) -> Optional[dict[str, Any]]:  # type: ignore[misc]
        return None

try:
    from skills.news_sentiment import get_news_sentiment
except ImportError:  # skill not shipped -> degrade gracefully, no news scoring

    def get_news_sentiment(symbol: str) -> dict[str, Any]:  # type: ignore[misc]
        return {"symbol": symbol, "score": 0.0, "signal": "neutral", "reason": "skill unavailable", "sources": 0}


SCREENER_MANIP_CONFIG = {
    "enabled": True,
    "check_interval_sec": 300,
    "thresholds": {
        "manipulation_score_pct": 80,      # composite manipulation risk score per stock
        "manipulation_rate_pct": 30,       # fraction of universe flagged = high severity
        "critical_rate_pct": 60,           # fraction of universe flagged = critical severity
        "ev_new_age_enabled": False,       # controlled rollout gate; flip to True to enable the boost
        "ev_new_age_boost_pct": 10,        # points added when EV/new-age criteria confirm symbol
        "news_sentiment_enabled": False,   # controlled rollout gate; flip to True to enable news sentiment boost
        "news_sentiment_boost_pct": 5,     # points added when news sentiment is negative
        "stuck_scan_minutes": 180,         # screener artifact freshness threshold
        "min_stocks_screened": 10,         # universe must have at least N stocks
    },
    "cooldown_sec": 300,  # 5 min between repeat manipulation actions for the same symbol
    "delivery_channels": ["web", "memory"],
}

# Screener artifacts watched for manipulation signals and pipeline health.
SCREENER_ARTIFACT_GLOBS = [
    "all_stocks_summary_*.csv",
    "screener_ev_*.csv",
    "*screener*checkpoint*.json",
    "*screener*results*.json",
]

REPO_ROOT = Path(__file__).resolve().parents[2]  # AI-Office/


@dataclass
class ManipSignal:
    """One manipulation signal detected in the screened universe."""

    symbol: str
    score: float
    reason: str
    source: str
    ev_new_age_score: Optional[float] = None
    ev_new_age: bool = False
    news_sentiment_score: Optional[float] = None
    news_sentiment: str = "neutral"


@dataclass
class ScreenerManipConfig:
    thresholds: dict


class ScreenerManipWatch:
    """Watches screener output for manipulation and triggers self-healing."""

    def __init__(
        self,
        config: dict | None = None,
        healing: FleetSelfHealing | None = None,
    ):
        self.config = {**SCREENER_MANIP_CONFIG, **(config or {})}
        # Deep-merge thresholds so a partial thresholds config (e.g. just the
        # ev_new_age_enabled rollout flag) keeps the default threshold values.
        if config and "thresholds" in config:
            self.config["thresholds"] = {
                **SCREENER_MANIP_CONFIG["thresholds"],
                **config["thresholds"],
            }
        self.memory = get_unified_memory()
        self.healing = healing or FleetSelfHealing()
        self._last_action: dict[str, float] = {}
        self._action_history: list[HealingAction] = []
        self._consecutive_failures: dict[str, int] = {}
        self._signals_history: list[dict] = []

    # ----------------------- Artifact fetching -----------------------

    def _artifact_paths(self) -> list[Path]:
        """All screener artifact paths in the repo root, newest first."""
        paths: list[Path] = []
        for pattern in SCREENER_ARTIFACT_GLOBS:
            paths.extend(REPO_ROOT.glob(pattern))
        # De-duplicate and sort by modification time, newest first.
        unique = {str(p): p for p in paths}
        return sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)

    def _load_csv(self, path: Path) -> list[dict[str, str]]:
        try:
            with path.open(newline="") as fh:
                return list(csv.DictReader(fh))
        except Exception as e:
            print(f"[screener_manip_watch] Failed to read {path}: {e}")
            return []

    def _load_json(self, path: Path) -> list[dict[str, Any]]:
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            print(f"[screener_manip_watch] Failed to read {path}: {e}")
            return []
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            return [dict(row) for row in data if isinstance(row, dict)]
        return []

    def fetch_screener_artifacts(self) -> list[dict[str, Any]]:
        """Load the latest screener artifacts as {path, mtime, rows, source}."""
        artifacts: list[dict[str, Any]] = []
        for path in self._artifact_paths():
            rows: list[dict[str, Any]] = []
            if path.suffix.lower() == ".csv":
                rows = self._load_csv(path)
            elif path.suffix.lower() == ".json":
                rows = self._load_json(path)
            else:
                continue
            artifacts.append(
                {
                    "path": str(path),
                    "source": path.name,
                    "rows": rows,
                    "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                }
            )
        return artifacts

    # ----------------------- Manipulation detection -----------------------

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            result = float(value)
            if math.isnan(result) or math.isinf(result):
                return None
            return result
        except (TypeError, ValueError):
            return None

    def _manipulation_score(self, row: dict[str, Any]) -> float:
        """Composite manipulation risk score for one screened stock (0-100)."""
        score = 0.0

        leverage = str(row.get("leverage_flag", "")).strip()
        if leverage == "High":
            score += 30
        elif leverage in ("Extreme", "Critical"):
            score += 45

        momentum = str(row.get("momentum_flag", "")).strip()
        if momentum in ("Parabolic", "Spike"):
            score += 30
        elif momentum in ("High", "Elevated"):
            score += 10

        pct_from_high = self._to_float(row.get("pct_from_52w_high"))
        if pct_from_high is not None:
            if pct_from_high >= 90:
                score += 25  # parabolic, within 10% of 52-week high
            elif pct_from_high <= -50:
                score += 10  # deep distress from highs

        pe = self._to_float(row.get("pe_ttm"))
        if pe is not None:
            if pe <= 0 or pe > 100:
                score += 15  # unprofessional or extreme multiple

        debt_to_equity = self._to_float(row.get("debt_to_equity"))
        if debt_to_equity is not None and debt_to_equity > 100:
            score += 15

        current_ratio = self._to_float(row.get("current_ratio"))
        if current_ratio is not None and current_ratio < 1:
            score += 10

        if row.get("ev_new_age") is True and self.config["thresholds"].get("ev_new_age_enabled", False):
            score += float(self.config["thresholds"].get("ev_new_age_boost_pct", 10))

        news = row.get("news_sentiment") or {}
        if (
            self.config["thresholds"].get("news_sentiment_enabled", False)
            and news.get("signal") == "negative"
        ):
            score += float(self.config["thresholds"].get("news_sentiment_boost_pct", 5))

        return min(score, 100.0)

    def _signals(self, rows: list[dict[str, Any]], source: str) -> list[ManipSignal]:
        threshold = self.config["thresholds"]["manipulation_score_pct"]
        signals: list[ManipSignal] = []
        for row in rows:
            symbol = str(row.get("symbol") or row.get("name") or "unknown").strip()
            score = self._manipulation_score(row)
            if score < threshold:
                continue
            reasons: list[str] = []
            leverage = str(row.get("leverage_flag", "")).strip()
            if leverage == "High":
                reasons.append("high leverage")
            momentum = str(row.get("momentum_flag", "")).strip()
            if momentum in ("Parabolic", "Spike"):
                reasons.append(f"momentum: {momentum}")
            pct = self._to_float(row.get("pct_from_52w_high"))
            if pct is not None and pct >= 90:
                reasons.append(f"within {100 - pct:.0f}% of 52-week high")
            if row.get("ev_new_age") is True:
                reasons.append("ev/new-age criteria confirmed")
            news = row.get("news_sentiment") or {}
            if news.get("signal") == "negative":
                reasons.append("negative news sentiment")
            signals.append(
                ManipSignal(
                    symbol=symbol,
                    score=score,
                    reason=", ".join(reasons) or f"composite score {score:.0f}",
                    source=source,
                    ev_new_age_score=self._to_float(row.get("ev_new_age_score")),
                    ev_new_age=bool(row.get("ev_new_age")),
                    news_sentiment_score=self._to_float(news.get("score")),
                    news_sentiment=str(news.get("signal", "neutral")),
                )
            )
        signals.sort(key=lambda s: s.score, reverse=True)
        return signals

    # ----------------------- Pipeline health -----------------------

    def _pipeline_healthy(self, artifacts: list[dict[str, Any]], rows: list[dict[str, Any]]) -> bool:
        if not artifacts:
            return False
        stuck_minutes = self.config["thresholds"]["stuck_scan_minutes"]
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)
        freshest = max(a["mtime"] for a in artifacts)
        if freshest < cutoff:
            return False
        min_stocks = self.config["thresholds"]["min_stocks_screened"]
        if len(rows) < min_stocks:
            return False
        return True

    # ----------------------- Cooldown -----------------------

    def _should_act(self, action_key: str) -> bool:
        now = time.time()
        last = self._last_action.get(action_key, 0)
        if now - last >= self.config["cooldown_sec"]:
            self._last_action[action_key] = now
            return True
        return False

    # ----------------------- Remediation -----------------------

    def _signal_actions(self, signals: list[ManipSignal]) -> list[HealingAction]:
        now = datetime.now(timezone.utc).isoformat()
        actions: list[HealingAction] = []
        for signal in signals:
            key = f"screener_manipulation_{signal.symbol}"
            if not self._should_act(key):
                continue
            details = {
                "symbol": signal.symbol,
                "score": signal.score,
                "reason": signal.reason,
                "source": signal.source,
            }
            self._record_action_outcome(key, True)
            actions.append(
                HealingAction(
                    id=f"heal-{int(time.time())}",
                    action_type="screener_manipulation_detected",
                    target=signal.symbol,
                    reason=(
                        f"Screener manipulation signal: {signal.symbol} "
                        f"(score {signal.score:.0f}, {signal.reason})"
                    ),
                    timestamp=now,
                    success=True,
                    details=details,
                )
            )
        return actions

    def _record_action_outcome(self, action_key: str, success: bool) -> None:
        """Track success/failure of an action for escalating backoff.

        A success resets consecutive failures for the key; a failure increments
        them. The cooldown timestamp set by _should_act is preserved so repeat
        actions stay throttled (the previous _record_action popped the
        timestamp right after _should_act set it, which silently disabled the
        per-symbol cooldown).
        """
        if success:
            self._consecutive_failures.pop(action_key, None)
        else:
            self._consecutive_failures[action_key] = (
                self._consecutive_failures.get(action_key, 0) + 1
            )

    # ----------------------- Cycle -----------------------

    async def run_once(self) -> dict[str, Any]:
        """Run one screener manipulation watch cycle.

        Triggers FleetSelfHealing checks based on screener signals:
        - pipeline stuck -> check_stuck_tasks
        - manipulation detected -> check_pool_saturation
        - critical manipulation -> run_once (full self-healing cycle)
        """
        if not self.config["enabled"]:
            return {"ok": True, "actions": [], "signals": [], "healing": None}

        artifacts = self.fetch_screener_artifacts()
        rows = [row for artifact in artifacts for row in artifact["rows"]]

        # Enrich each row with EV/new-age criteria and news sentiment from the
        # external skills. Any skill failure degrades gracefully: the row scores
        # without the boost from that skill.
        def _enrich(row: dict[str, Any]) -> dict[str, Any]:
            enriched = dict(row)
            symbol = str(row.get("symbol") or row.get("name") or "").strip()
            if not symbol:
                return enriched
            try:
                criteria = get_ev_criteria(symbol)
            except Exception:
                criteria = None
            if criteria:
                if criteria.get("ev_new_age") is not None:
                    enriched["ev_new_age"] = bool(criteria["ev_new_age"])
                score = criteria.get("ev_new_age_score")
                if score is not None:
                    enriched["ev_new_age_score"] = score
            if self.config["thresholds"].get("news_sentiment_enabled", False):
                try:
                    sentiment = get_news_sentiment(symbol)
                except Exception:
                    sentiment = {"signal": "neutral", "score": 0.0}
                if sentiment:
                    enriched["news_sentiment"] = sentiment
            return enriched

        signals: list[ManipSignal] = []
        for artifact in artifacts:
            signals.extend(self._signals([_enrich(row) for row in artifact["rows"]], artifact["source"]))

        now = datetime.now(timezone.utc).isoformat()
        actions: list[HealingAction] = []
        actions.extend(self._signal_actions(signals))

        healing_metrics = self.healing.fetch_fleet_metrics()
        healing_result: dict[str, Any] | None = None
        healing_actions: list[dict[str, Any]] = []

        pipeline_ok = self._pipeline_healthy(artifacts, rows)
        manipulation_rate = len(signals) / max(len(rows), 1) if rows else 0.0

        if not pipeline_ok:
            if self._should_act("screener_pipeline_stuck"):
                stuck_actions = self.healing.check_stuck_tasks(healing_metrics)
                actions.extend(stuck_actions)
                healing_actions.extend(
                    {"type": a.action_type, "target": a.target, "reason": a.reason, "success": a.success}
                    for a in stuck_actions
                )
                self._record_action_outcome("screener_pipeline_stuck", bool(stuck_actions))
        else:
            self._record_action_outcome("screener_pipeline_stuck", True)

        if manipulation_rate >= self.config["thresholds"]["critical_rate_pct"] / 100.0 and signals:
            if self._should_act("screener_manipulation_critical"):
                healing_result = await self.healing.run_once()
                healing_actions = self._healing_result_actions(healing_result)
                for healing_dict in self._actions_from_result(healing_result):
                    actions.append(
                        HealingAction(
                            id=f"heal-{int(time.time())}-{len(actions)}",
                            action_type=healing_dict.get("type", "unknown"),
                            target=healing_dict.get("target", ""),
                            reason=healing_dict.get("reason", ""),
                            timestamp=now,
                            success=bool(healing_dict.get("success", False)),
                            details={
                                k: v
                                for k, v in healing_dict.items()
                                if k not in ("type", "target", "reason", "success")
                            },
                        )
                    )
                self._record_action_outcome("screener_manipulation_critical", healing_result.get("ok", False))
        elif manipulation_rate >= self.config["thresholds"]["manipulation_rate_pct"] / 100.0 and signals:
            if self._should_act("screener_manipulation_high"):
                saturation_actions = self.healing.check_pool_saturation(healing_metrics)
                actions.extend(saturation_actions)
                healing_actions.extend(
                    {"type": a.action_type, "target": a.target, "reason": a.reason, "success": a.success}
                    for a in saturation_actions
                )
                self._record_action_outcome("screener_manipulation_high", bool(saturation_actions))

        # Record actions, log to memory, persist observability state.
        for action in actions:
            self._action_history.append(action)
            self._log_action(action)

        self.memory.set_preference(
            "screener_manip_watch",
            {
                "last_run": now,
                "pipeline_ok": pipeline_ok,
                "rows_screened": len(rows),
                "manipulation_signals": len(signals),
                "manipulation_rate": round(manipulation_rate, 4),
                "ev_new_age_signals": sum(1 for s in signals if s.ev_new_age),
                "news_sentiment_signals": sum(1 for s in signals if s.news_sentiment == "negative"),
                "actions": [
                    {
                        "id": a.id,
                        "type": a.action_type,
                        "target": a.target,
                        "reason": a.reason,
                        "success": a.success,
                    }
                    for a in self._action_history[-50:]
                ],
                "signals": [
                    {
                        "symbol": s.symbol,
                        "score": s.score,
                        "reason": s.reason,
                        "source": s.source,
                        "ev_new_age": s.ev_new_age,
                        "ev_new_age_score": s.ev_new_age_score,
                        "news_sentiment": s.news_sentiment,
                        "news_sentiment_score": s.news_sentiment_score,
                    }
                    for s in signals[:50]
                ],
            },
        )
        self._signals_history.append(
            {"timestamp": now, "signals": [vars(s) for s in signals], "actions": len(actions)}
        )
        self._signals_history = self._signals_history[-200:]

        return {
            "ok": True,
            "actions": [
                {
                    "id": a.id,
                    "type": a.action_type,
                    "target": a.target,
                    "reason": a.reason,
                    "success": a.success,
                    "details": a.details,
                }
                for a in actions
            ],
            "signals": [
                {
                    "symbol": s.symbol,
                    "score": s.score,
                    "reason": s.reason,
                    "source": s.source,
                    "ev_new_age": s.ev_new_age,
                    "ev_new_age_score": s.ev_new_age_score,
                    "news_sentiment": s.news_sentiment,
                    "news_sentiment_score": s.news_sentiment_score,
                }
                for s in signals
            ],
            "pipeline_ok": pipeline_ok,
            "rows_screened": len(rows),
            "healing": {
                "result": healing_result,
                "actions": healing_actions,
            },
        }

    def _actions_from_result(self, result: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
        if not result:
            return []
        return result.get("actions", [])

    def _healing_result_actions(self, result: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._actions_from_result(result)

    # ----------------------- Logging / persistence -----------------------

    def _log_action(self, action: HealingAction) -> None:
        self.memory.add_message(
            "screener_manip_watch",
            "system",
            f"Screener watch action: {action.action_type} on {action.target} - {action.reason}",
            {"action": action.__dict__},
        )

    def get_action_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "id": a.id,
                "type": a.action_type,
                "target": a.target,
                "reason": a.reason,
                "timestamp": a.timestamp,
                "success": a.success,
                "details": a.details,
            }
            for a in self._action_history[-limit:]
        ]

    async def run_loop(self):
        """Run continuous screener manipulation watch loop."""
        print(f"[screener_manip_watch] Starting loop (interval: {self.config['check_interval_sec']}s)")
        while True:
            try:
                result = await self.run_once()
                if result.get("actions"):
                    print(f"[screener_manip_watch] Actions taken: {len(result['actions'])}")
                if result.get("signals"):
                    print(f"[screener_manip_watch] Manipulation signals: {len(result['signals'])}")
            except Exception as e:
                print(f"[screener_manip_watch] Loop error: {e}")
            await asyncio.sleep(self.config["check_interval_sec"])


async def main():
    """Entry point for running the screener manipulation watch loop."""
    watch = ScreenerManipWatch()
    print(f"[screener_manip_watch] Starting loop (interval: {watch.config['check_interval_sec']}s)")
    while True:
        try:
            result = await watch.run_once()
            if result.get("actions"):
                print(f"[screener_manip_watch] Actions taken: {len(result['actions'])}")
            if result.get("signals"):
                print(f"[screener_manip_watch] Manipulation signals: {len(result['signals'])}")
        except Exception as e:
            print(f"[screener_manip_watch] Loop error: {e}")
        await asyncio.sleep(watch.config["check_interval_sec"])


if __name__ == "__main__":
    asyncio.run(main())
