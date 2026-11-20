"""
Changelog management for THE CLAUDE COMPANY.

Changelog entries are stored as JSON files:
    ~/.openclaw/changelog/{version}.json

Each entry:
    {
        "version": "1.2.3",
        "date": "2026-11-18",
        "changes": [
            {"type": "added", "description": "...", "component": "..."},
            ...
        ],
        "created_at": "2026-11-18T02:45:00Z"
    }
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(os.path.expanduser("~/.openclaw/changelog"))
BASE_DIR.mkdir(parents=True, exist_ok=True)

_VALID_TYPES = {"added", "changed", "fixed", "removed", "security"}
_VERSION_RE = re.compile(
    r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)


def _changelog_file(version: str) -> Path:
    return BASE_DIR / f"{version}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _version_key(version: str) -> tuple:
    """Parse a version string into a comparable tuple (major, minor, patch, pre, build)."""
    match = _VERSION_RE.match(version.strip())
    if not match:
        raise ValueError(f"Invalid version string: {version!r}")
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) is not None else 0
    patch = int(match.group(3)) if match.group(3) is not None else 0
    pre = match.group(4) or ""
    build = match.group(5) or ""
    return (major, minor, patch, pre, build)


def _validate_change(change: Any) -> None:
    """Validate a single change dict."""
    if not isinstance(change, dict):
        raise ValueError("Each change must be a dict")
    change_type = change.get("type")
    if change_type not in _VALID_TYPES:
        raise ValueError(
            f"Invalid change type: {change_type!r}. Must be one of {sorted(_VALID_TYPES)}"
        )
    description = change.get("description", "")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Each change must have a non-empty 'description' string")
    component = change.get("component", "")
    if not isinstance(component, str):
        raise ValueError("Each change must have a 'component' string")


def add_changelog_entry(version: str, date: str, changes: list[dict]) -> dict:
    """Add a changelog entry.

    Each change: {"type": "added|changed|fixed|removed|security", "description": str, "component": str}

    Returns: {"version": ..., "date": ..., "changes": [...], "created_at": ...}
    """
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version must be a non-empty string")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"date must be in YYYY-MM-DD format: {date!r}")
    if not isinstance(changes, list):
        raise ValueError("changes must be a list")
    for change in changes:
        _validate_change(change)

    entry: Dict[str, Any] = {
        "version": version.strip(),
        "date": date,
        "changes": [dict(c) for c in changes],
        "created_at": _now_iso(),
    }

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_changelog_file(version.strip()), "w") as f:
        json.dump(entry, f, indent=2)

    return entry


def get_changelog(version: str = None) -> Optional[Dict[str, Any]]:
    """Get a changelog entry by version, or all entries sorted by date descending."""
    if version is not None:
        path = _changelog_file(version)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    entries: List[Dict[str, Any]] = []
    if BASE_DIR.exists():
        for path in sorted(BASE_DIR.glob("*.json")):
            try:
                entries.append(json.loads(path.read_text()))
            except (json.JSONDecodeError, ValueError, OSError):
                continue
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    return entries


def generate_changelog_md() -> str:
    """Generate a markdown-formatted changelog from all stored entries."""
    entries = get_changelog()
    if not entries:
        return "# Changelog\n\nNo changelog entries found.\n"

    type_label = {
        "added": "Added",
        "changed": "Changed",
        "fixed": "Fixed",
        "removed": "Removed",
        "security": "Security",
    }
    type_order = ("added", "changed", "fixed", "removed", "security")

    lines: List[str] = ["# Changelog", ""]
    for entry in entries:
        version = entry.get("version", "unknown")
        date = entry.get("date", "")
        lines.append(f"## [{version}] - {date}")
        lines.append("")

        changes = entry.get("changes", [])
        by_type: Dict[str, List[dict]] = {}
        for change in changes:
            by_type.setdefault(change.get("type", "changed"), []).append(change)

        for change_type in type_order:
            items = by_type.get(change_type)
            if not items:
                continue
            lines.append(f"### {type_label[change_type]}")
            lines.append("")
            for change in items:
                component = change.get("component", "")
                description = change.get("description", "")
                if component:
                    lines.append(f"- **{component}**: {description}")
                else:
                    lines.append(f"- {description}")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def get_latest_version() -> Optional[str]:
    """Return the latest version string, or None if no entries exist."""
    entries = get_changelog()
    if not entries:
        return None
    try:
        latest = max(entries, key=lambda e: _version_key(e.get("version", "0.0.0")))
    except ValueError:
        latest = max(entries, key=lambda e: e.get("version", ""))
    return latest.get("version")


def compare_versions(version1: str, version2: str) -> int:
    """Compare two version strings.

    Returns -1 if version1 < version2, 0 if equal, 1 if version1 > version2.
    """
    v1 = _version_key(version1)
    v2 = _version_key(version2)
    if v1 < v2:
        return -1
    if v1 > v2:
        return 1
    return 0
