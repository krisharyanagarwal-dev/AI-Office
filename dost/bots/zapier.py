"""
Zapier webhook triggers for THE CLAUDE COMPANY.

Each Zapier trigger is a subscription from a workspace to a single HTTP
endpoint that receives POST notifications when a specific event fires.

Storage: ~/.openclaw/zapier/zapiers.json  (dict keyed by zapier_id)

Allowed events:
    "task.done", "task.error", "finding.contested",
    "cost.alert", "debate.complete"
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

ZAPIER_DIR = Path(os.path.expanduser("~/.openclaw/zapier"))
ZAPIER_DIR.mkdir(parents=True, exist_ok=True)
ZAPIERS_FILE = ZAPIER_DIR / "zapiers.json"

ALLOWED_EVENTS = {
    "task.done",
    "task.error",
    "finding.contested",
    "cost.alert",
    "debate.complete",
}

REQUEST_TIMEOUT = 10  # seconds


def _load_zapiers() -> Dict[str, dict]:
    if not ZAPIERS_FILE.exists():
        return {}
    try:
        with open(ZAPIERS_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_zapiers(zapiers: Dict[str, dict]) -> None:
    with open(ZAPIERS_FILE, "w") as f:
        json.dump(zapiers, f, indent=2)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_zapier_trigger(
    workspace_id: str,
    event_type: str,
    webhook_url: str,
) -> dict:
    """Create a Zapier webhook trigger for a workspace.

    Returns the created trigger record:
        {"zapier_id", "workspace_id", "event_type", "webhook_url", "created_at"}
    """
    if event_type not in ALLOWED_EVENTS:
        raise ValueError(
            f"Invalid event_type: {event_type!r}. Allowed: {sorted(ALLOWED_EVENTS)}"
        )

    zapier_id = f"zap-{uuid.uuid4().hex[:12]}"
    record: Dict[str, Any] = {
        "zapier_id": zapier_id,
        "workspace_id": workspace_id,
        "event_type": event_type,
        "webhook_url": webhook_url,
        "created_at": _now(),
    }

    zapiers = _load_zapiers()
    zapiers[zapier_id] = record
    _save_zapiers(zapiers)

    return record


def get_zapier_trigger(zapier_id: str) -> Optional[dict]:
    """Get a Zapier trigger by ID, or None if it does not exist."""
    zapiers = _load_zapiers()
    return zapiers.get(zapier_id)


def list_zapier_triggers(workspace_id: str) -> List[dict]:
    """List all Zapier triggers for a workspace."""
    zapiers = _load_zapiers()
    return [
        record
        for record in zapiers.values()
        if record.get("workspace_id") == workspace_id
    ]


def delete_zapier_trigger(zapier_id: str) -> bool:
    """Delete a Zapier trigger by ID. Returns True if deleted, False if not found."""
    zapiers = _load_zapiers()
    if zapier_id not in zapiers:
        return False
    del zapiers[zapier_id]
    _save_zapiers(zapiers)
    return True


def trigger_zapier_webhook(zapier_id: str, event_type: str, payload: dict) -> bool:
    """Fire a single Zapier webhook.

    POSTs the payload to the trigger's webhook URL.

    Returns True if the endpoint responded with a 2xx status, False otherwise.
    """
    record = get_zapier_trigger(zapier_id)
    if record is None:
        return False

    url = record["webhook_url"]

    body = json.dumps(
        {
            "event": event_type,
            "zapier_id": zapier_id,
            "workspace_id": record.get("workspace_id"),
            "payload": payload,
            "timestamp": _now(),
        },
        separators=(",", ":"),
    ).encode("utf-8")

    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "dost-zapier/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status = resp.getstatus() if hasattr(resp, "getstatus") else resp.status
            return 200 <= status < 300
    except HTTPError as exc:
        return 200 <= exc.code < 300
    except (URLError, OSError, ValueError):
        return False


def trigger_event(
    workspace_id: str,
    event_type: str,
    payload: dict,
) -> List[str]:
    """Trigger all Zapier webhooks for a workspace on an event type.

    Returns the list of zapier IDs that were triggered (attempted).
    """
    triggered: List[str] = []
    for record in list_zapier_triggers(workspace_id):
        zapier_id = record["zapier_id"]
        if record.get("event_type") == event_type:
            trigger_zapier_webhook(zapier_id, event_type, payload)
            triggered.append(zapier_id)
    return triggered
