"""
Webhook subscriptions for THE CLAUDE COMPANY.

Each webhook is a subscription from a workspace to an HTTP endpoint that
receives POST notifications when subscribed events fire.

Storage: ~/.openclaw/webhooks/webhooks.json  (dict keyed by webhook_id)

Allowed events:
    "task.done", "task.error", "finding.contested",
    "cost.alert", "debate.complete"
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

WEBHOOK_DIR = Path(os.path.expanduser("~/.openclaw/webhooks"))
WEBHOOK_DIR.mkdir(parents=True, exist_ok=True)
WEBHOOKS_FILE = WEBHOOK_DIR / "webhooks.json"

ALLOWED_EVENTS = {
    "task.done",
    "task.error",
    "finding.contested",
    "cost.alert",
    "debate.complete",
}

SECRET_HEADER = "X-Webhook-Secret"
SIGNATURE_HEADER = "X-Hub-Signature-256"
REQUEST_TIMEOUT = 10  # seconds


def _load_webhooks() -> Dict[str, dict]:
    if not WEBHOOKS_FILE.exists():
        return {}
    try:
        with open(WEBHOOKS_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_webhooks(webhooks: Dict[str, dict]) -> None:
    with open(WEBHOOKS_FILE, "w") as f:
        json.dump(webhooks, f, indent=2)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_webhook(
    workspace_id: str,
    url: str,
    events: list,
    secret: str = None,
) -> dict:
    """Create a webhook subscription for a workspace.

    Returns the created webhook record:
        {"webhook_id", "workspace_id", "url", "events", "secret", "created_at"}
    """
    invalid = [e for e in events if e not in ALLOWED_EVENTS]
    if invalid:
        raise ValueError(f"Invalid event(s): {invalid}. Allowed: {sorted(ALLOWED_EVENTS)}")

    webhook_id = f"wh-{uuid.uuid4().hex[:12]}"
    if secret is None:
        secret = uuid.uuid4().hex

    record: Dict[str, Any] = {
        "webhook_id": webhook_id,
        "workspace_id": workspace_id,
        "url": url,
        "events": list(events),
        "secret": secret,
        "created_at": _now(),
    }

    webhooks = _load_webhooks()
    webhooks[webhook_id] = record
    _save_webhooks(webhooks)

    return record


def get_webhook(webhook_id: str) -> Optional[dict]:
    """Get a webhook by ID, or None if it does not exist."""
    webhooks = _load_webhooks()
    return webhooks.get(webhook_id)


def list_webhooks(workspace_id: str) -> List[dict]:
    """List all webhooks for a workspace."""
    webhooks = _load_webhooks()
    return [
        record
        for record in webhooks.values()
        if record.get("workspace_id") == workspace_id
    ]


def delete_webhook(webhook_id: str) -> bool:
    """Delete a webhook by ID. Returns True if deleted, False if not found."""
    webhooks = _load_webhooks()
    if webhook_id not in webhooks:
        return False
    del webhooks[webhook_id]
    _save_webhooks(webhooks)
    return True


def _sign_payload(secret: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def trigger_webhook(webhook_id: str, event_type: str, payload: dict) -> bool:
    """Fire a single webhook.

    POSTs the payload to the webhook URL and includes the webhook secret in
    the ``X-Webhook-Secret`` header plus an HMAC signature in
    ``X-Hub-Signature-256`` for signature verification.

    Returns True if the endpoint responded with a 2xx status, False otherwise.
    """
    record = get_webhook(webhook_id)
    if record is None:
        return False

    url = record["url"]
    secret = record.get("secret", "")

    body = json.dumps(
        {
            "event": event_type,
            "webhook_id": webhook_id,
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
            SECRET_HEADER: secret,
            SIGNATURE_HEADER: _sign_payload(secret, payload),
            "User-Agent": "dost-webhooks/1.0",
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
    """Trigger all webhooks for a workspace on an event type.

    Returns the list of webhook IDs that were triggered (attempted).
    """
    triggered: List[str] = []
    for record in list_webhooks(workspace_id):
        webhook_id = record["webhook_id"]
        if event_type in record.get("events", []):
            trigger_webhook(webhook_id, event_type, payload)
            triggered.append(webhook_id)
    return triggered
