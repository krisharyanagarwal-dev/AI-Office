"""Dost skill: EV / new-age screener criteria.

Internal skill interface decoupling screener-manip-watch (and other
consumers) from vendor file formats. Reads the latest
`screener_ev_*.csv` artifact produced by `ops.screener_ingest` and exposes:

- get_ev_criteria(symbol) -> dict | None
- get_all_ev_criteria() -> list[dict]
- is_ev_new_age(symbol) -> bool        (ev_new_age_score >= 70)
- latest_artifact_path() -> Path | None

Lazy loads + caches per cycle: the in-memory cache refreshes whenever the
latest artifact path or its mtime changes, and degrades to empty when no
artifact exists. Read-only — no network, no credentials.

Follows the dost skill registry pattern (SKILL_MANIFEST) so
dost/skills/registry.py can discover and register it.
"""

from __future__ import annotations

import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `import ops` if needed)

REPO_ROOT = Path(__file__).resolve().parents[2]  # AI-Office/

EV_NEW_AGE_ARTIFACT_GLOB = "screener_ev_*.csv"
EV_NEW_AGE_THRESHOLD = 70

CSV_NUMERIC_FIELDS = (
    "market_cap",
    "revenue_growth",
    "ev_ebitda",
    "pe_ttm",
    "debt_to_equity",
    "current_ratio",
    "pct_from_52w_high",
    "ev_new_age_score",
)

CSV_STRING_FIELDS = ("sector", "momentum_flag", "leverage_flag")


@dataclass
class EVIntegrationConfig:
    artifact_root: Path = REPO_ROOT
    threshold: int = EV_NEW_AGE_THRESHOLD


SKILL_MANIFEST = {
    "name": "screener_ev_integration",
    "version": "1.0.0",
    "description": "EV/new-age screener criteria skill backed by screener_ev_*.csv artifacts",
    "author": "dost",
    "dependencies": [],
    "entry_point": "get_all_ev_criteria",
    "module_file": "screener_ev_integration.py",
    "test_file": "test_screener_ev_integration.py",
    "config_schema": {},
    "default_config": {},
    "tags": ["screener", "ev", "new-age", "ingestion"],
    "enabled": True,
}


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


class ScreenerEVIntegration:
    """Read-only view over the latest EV / new-age screener artifact."""

    def __init__(self, config: EVIntegrationConfig | None = None):
        self.config = config or EVIntegrationConfig()
        self._cache: dict[str, dict[str, Any]] = {}
        self._all: list[dict[str, Any]] = []
        self._cached_artifact: Optional[Path] = None
        self._cached_mtime: Optional[float] = None

    def latest_artifact_path(self) -> Optional[Path]:
        """Most recent screener_ev_*.csv, or None when none exists."""
        paths = sorted(
            self.config.artifact_root.glob(EV_NEW_AGE_ARTIFACT_GLOB),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return paths[0] if paths else None

    def _reload_if_needed(self) -> None:
        path = self.latest_artifact_path()
        mtime = path.stat().st_mtime if path else None
        if (
            path is not None
            and path == self._cached_artifact
            and mtime == self._cached_mtime
        ):
            return
        self._cached_artifact = path
        self._cached_mtime = mtime
        self._load(path)

    def _load(self, path: Optional[Path]) -> None:
        self._cache = {}
        self._all = []
        if path is None:
            return
        try:
            with path.open(newline="") as fh:
                for row in csv.DictReader(fh):
                    symbol = str(row.get("symbol") or "").strip().upper()
                    if not symbol:
                        continue
                    criteria = self._parse_row(row)
                    self._cache[symbol] = criteria
                    self._all.append(criteria)
        except (OSError, csv.Error):
            self._cache = {}
            self._all = []

    def _parse_row(self, row: dict[str, str]) -> dict[str, Any]:
        criteria: dict[str, Any] = {"symbol": str(row.get("symbol") or "").strip()}
        for field in CSV_NUMERIC_FIELDS:
            criteria[field] = _to_float(row.get(field))
        for field in CSV_STRING_FIELDS:
            criteria[field] = str(row.get(field) or "").strip()
        score = criteria.get("ev_new_age_score")
        criteria["ev_new_age"] = bool(
            score is not None and score >= self.config.threshold
        )
        return criteria

    def get_ev_criteria(self, symbol: str) -> Optional[dict[str, Any]]:
        """Criteria for one symbol from the latest artifact, or None."""
        self._reload_if_needed()
        key = str(symbol).strip().upper()
        return self._cache.get(key)

    def get_all_ev_criteria(self) -> list[dict[str, Any]]:
        """All symbols' criteria from the latest artifact."""
        self._reload_if_needed()
        return list(self._all)

    def is_ev_new_age(self, symbol: str) -> bool:
        """True when the symbol's ev_new_age_score meets the threshold."""
        criteria = self.get_ev_criteria(symbol)
        score = criteria.get("ev_new_age_score") if criteria else None
        return bool(score is not None and score >= self.config.threshold)


# Default process-wide instance used by module-level convenience functions.
EV_INTEGRATION = ScreenerEVIntegration()


def get_ev_criteria(symbol: str) -> Optional[dict[str, Any]]:
    return EV_INTEGRATION.get_ev_criteria(symbol)


def get_all_ev_criteria() -> list[dict[str, Any]]:
    return EV_INTEGRATION.get_all_ev_criteria()


def is_ev_new_age(symbol: str) -> bool:
    return EV_INTEGRATION.is_ev_new_age(symbol)


def latest_artifact_path() -> Optional[Path]:
    return EV_INTEGRATION.latest_artifact_path()
