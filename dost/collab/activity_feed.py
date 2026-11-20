"""
Activity feed and @mentions for THE CLAUDE COMPANY.

Each workspace stores an append-only activity log as JSONL files, one per day:
    ~/.openclaw/workspaces/{workspace_id}/activity/{YYYY-MM-DD}.jsonl

Each activity record:
    {
        "activity_id": "...",
        "actor_email": "...",
        "action": "...",
        "target_type": "...",
        "target_id": "...",
        "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
        "metadata": {...}
    }
"""

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

MENTION_RE = re.compile(r"@([\w.+-]+)")
_TRAILING_PUNCT = ".,;:!?)\"'"


def _activity_dir(workspace_id: str) -> Path:
    return WORKSPACE_DIR / workspace_id / "activity"


def _activity_file(workspace_id: str, date_str: str) -> Path:
    return _activity_dir(workspace_id) / f"{date_str}.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _read_jsonl_lines(path: Path) -> List[dict]:
    """Read all valid JSON objects from a JSONL file."""
    records: List[dict] = []
    if not path.exists():
        return records
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return records


def log_activity(
    workspace_id: str,
    actor_email: str,
    action: str,
    target_type: str,
    target_id: str,
    metadata: Optional[dict] = None,
) -> dict:
    """Log an activity event and append it to the workspace activity log.

    Returns the activity record that was stored.
    """
    activity_id = f"act-{uuid.uuid4().hex[:8]}"
    timestamp = _now_iso()
    record = {
        "activity_id": activity_id,
        "actor_email": actor_email,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "timestamp": timestamp,
        "metadata": metadata if metadata is not None else {},
    }

    act_dir = _activity_dir(workspace_id)
    act_dir.mkdir(parents=True, exist_ok=True)
    with open(_activity_file(workspace_id, _today()), "a") as f:
        f.write(json.dumps(record) + "\n")

    return record


def get_activity_feed(workspace_id: str, limit: int = 50) -> List[dict]:
    """Return recent activity across the workspace, newest first."""
    act_dir = _activity_dir(workspace_id)
    if not act_dir.exists():
        return []

    activities: List[dict] = []
    for path in sorted(act_dir.glob("*.jsonl")):
        activities.extend(_read_jsonl_lines(path))

    activities.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    return activities[:limit]


def get_user_activities(
    workspace_id: str, user_email: str, limit: int = 50
) -> List[dict]:
    """Return activities performed by a specific user, newest first."""
    all_activities = get_activity_feed(workspace_id)
    user_activities = [
        a for a in all_activities if a.get("actor_email") == user_email
    ]
    return user_activities[:limit]


def extract_mentions(text: str) -> List[str]:
    """Extract @mention handles from text, in order of first appearance.

    Handles are returned without the leading ``@`` and de-duplicated.
    Trailing punctuation is stripped.
    """
    mentions: List[str] = []
    seen = set()
    for match in MENTION_RE.finditer(text):
        handle = match.group(1).rstrip(_TRAILING_PUNCT)
        if not handle or handle in seen:
            continue
        seen.add(handle)
        mentions.append(handle)
    return mentions


def notify_mentions(
    text: str, workspace_id: str, sender_email: str
) -> List[str]:
    """Return the list of mentioned user emails found in ``text``.

    Mentions are extracted from the text. If the workspace has a users file,
    only mentions matching an existing workspace user email are returned.
    """
    mentioned = extract_mentions(text)

    users_path = _activity_dir(workspace_id).parent / "users.json"
    if users_path.exists():
        try:
            users = json.loads(users_path.read_text())
            valid_emails = {
                email.lower() for email in users.keys()
            } | {
                (u.get("email") or "").lower()
                for u in users.values()
                if isinstance(u, dict)
            }
            mentioned = [
                m for m in mentioned if m.lower() in valid_emails
            ]
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    return mentioned
