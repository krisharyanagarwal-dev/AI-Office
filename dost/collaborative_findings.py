"""
Collaborative findings review for THE CLAUDE COMPANY.

Each finding is stored per-workspace under:
    ~/.openclaw/workspaces/{workspace_id}/findings/{finding_id}/
with comments, reactions, and assignments living as JSON files below it.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

FINDINGS_DIR = "findings"
COMMENTS_DIR = "comments"
REACTIONS_DIR = "reactions"
ASSIGNMENT_FILE = "assignment.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding_dir(workspace_id: str, finding_id: str) -> Path:
    return WORKSPACE_DIR / workspace_id / FINDINGS_DIR / finding_id


def _comments_dir(workspace_id: str, finding_id: str) -> Path:
    d = _finding_dir(workspace_id, finding_id) / COMMENTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reactions_dir(workspace_id: str, finding_id: str) -> Path:
    d = _finding_dir(workspace_id, finding_id) / REACTIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def add_finding_comment(
    finding_id: str, workspace_id: str, user_email: str, comment: str
) -> dict:
    """Add a comment to a finding.

    Returns:
        {"comment_id", "finding_id", "user_email", "comment", "created_at"}
    Stored at ~/.openclaw/workspaces/{workspace_id}/findings/{finding_id}/comments/{comment_id}.json
    """
    comment_id = f"cmt-{uuid.uuid4().hex[:8]}"
    record = {
        "comment_id": comment_id,
        "finding_id": finding_id,
        "user_email": user_email,
        "comment": comment,
        "created_at": _now_iso(),
    }
    _write_json(_comments_dir(workspace_id, finding_id) / f"{comment_id}.json", record)
    return record


def get_finding_comments(finding_id: str, workspace_id: str) -> list[dict]:
    """List all comments for a finding, newest first."""
    comment_dir = _finding_dir(workspace_id, finding_id) / COMMENTS_DIR
    comments: list[dict] = []
    if comment_dir.exists():
        for path in comment_dir.glob("*.json"):
            record = _read_json(path)
            if record:
                comments.append(record)
    comments.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return comments


def add_finding_reaction(
    finding_id: str, workspace_id: str, user_email: str, reaction: str
) -> dict:
    """Add an emoji reaction to a finding.

    Returns:
        {"reaction_id", "finding_id", "user_email", "reaction", "created_at"}
    Stored at ~/.openclaw/workspaces/{workspace_id}/findings/{finding_id}/reactions/{reaction_id}.json
    """
    reaction_id = f"rct-{uuid.uuid4().hex[:8]}"
    record = {
        "reaction_id": reaction_id,
        "finding_id": finding_id,
        "user_email": user_email,
        "reaction": reaction,
        "created_at": _now_iso(),
    }
    _write_json(
        _reactions_dir(workspace_id, finding_id) / f"{reaction_id}.json", record
    )
    return record


def get_finding_reactions(finding_id: str, workspace_id: str) -> dict:
    """List reactions grouped by type (emoji).

    Returns:
        {reaction: [{"reaction_id", "user_email", "created_at"}, ...]}
    """
    reaction_dir = _finding_dir(workspace_id, finding_id) / REACTIONS_DIR
    grouped: dict[str, list[dict]] = {}
    if reaction_dir.exists():
        for path in reaction_dir.glob("*.json"):
            record = _read_json(path)
            if not record:
                continue
            grouped.setdefault(record.get("reaction", ""), []).append(
                {
                    "reaction_id": record.get("reaction_id"),
                    "user_email": record.get("user_email"),
                    "created_at": record.get("created_at"),
                }
            )
    for reaction in grouped:
        grouped[reaction].sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return grouped


def assign_finding(finding_id: str, workspace_id: str, user_email: str) -> bool:
    """Assign a finding to a user for review. Returns True on success."""
    f_dir = _finding_dir(workspace_id, finding_id)
    f_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        f_dir / ASSIGNMENT_FILE,
        {
            "finding_id": finding_id,
            "workspace_id": workspace_id,
            "user_email": user_email,
            "assigned_at": _now_iso(),
        },
    )
    return True


def get_assigned_findings(workspace_id: str, user_email: str) -> list[dict]:
    """List findings assigned to a user within a workspace."""
    findings_dir = WORKSPACE_DIR / workspace_id / FINDINGS_DIR
    assigned: list[dict] = []
    if not findings_dir.exists():
        return assigned
    for f_dir in findings_dir.iterdir():
        if not f_dir.is_dir():
            continue
        assignment = _read_json(f_dir / ASSIGNMENT_FILE)
        if assignment and assignment.get("user_email") == user_email:
            assigned.append(
                {
                    "finding_id": assignment.get("finding_id"),
                    "workspace_id": assignment.get("workspace_id"),
                    "user_email": assignment.get("user_email"),
                    "assigned_at": assignment.get("assigned_at"),
                }
            )
    assigned.sort(key=lambda a: a.get("assigned_at", ""), reverse=True)
    return assigned
