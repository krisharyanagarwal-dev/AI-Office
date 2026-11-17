"""API marketplace for THE CLAUDE COMPANY.

Provides a catalog of third-party APIs that workspaces can subscribe to and
invoke. All state is persisted as JSON under
``~/.openclaw/api_marketplace/``:

* ``catalog.json``   - available APIs (the marketplace catalog)
* ``subscriptions.json`` - active workspace subscriptions
"""

import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(os.path.expanduser("~/.openclaw"))
MARKETPLACE_DIR = BASE_DIR / "api_marketplace"
CATALOG_FILE = MARKETPLACE_DIR / "catalog.json"
SUBSCRIPTIONS_FILE = MARKETPLACE_DIR / "subscriptions.json"


# ---------------------------------------------------------------------------
# Seed catalog
# ---------------------------------------------------------------------------

_DEFAULT_CATALOG = [
    {
        "api_id": "weather-v1",
        "name": "Global Weather API",
        "description": "Current weather and forecasts for any location worldwide.",
        "category": "weather",
        "version": "1.0.0",
        "endpoint": "https://api.example.com/weather",
        "auth_required": True,
        "rate_limit": "60 requests/minute",
        "pricing": {"model": "per_call", "cost_units": 1, "currency": "USD"},
        "documentation_url": "https://docs.example.com/weather",
        "examples": [
            {
                "method": "GET",
                "endpoint": "/weather?q=London",
                "description": "Current weather in London",
            },
            {
                "method": "GET",
                "endpoint": "/forecast?q=London&days=3",
                "description": "3-day forecast for London",
            },
        ],
    },
    {
        "api_id": "translation-v1",
        "name": "Text Translation API",
        "description": "Translate text between 100+ languages using neural models.",
        "category": "translation",
        "version": "2.1.0",
        "endpoint": "https://api.example.com/translate",
        "auth_required": True,
        "rate_limit": "100 requests/minute",
        "pricing": {"model": "per_character", "cost_units": 1, "currency": "USD"},
        "documentation_url": "https://docs.example.com/translate",
        "examples": [
            {
                "method": "POST",
                "endpoint": "/translate",
                "payload": {"text": "Hello", "target": "es"},
                "description": "Translate 'Hello' to Spanish",
            }
        ],
    },
    {
        "api_id": "web-search-v1",
        "name": "Web Search API",
        "description": "Search the public web and return ranked results with snippets.",
        "category": "search",
        "version": "1.3.0",
        "endpoint": "https://api.example.com/search",
        "auth_required": True,
        "rate_limit": "30 requests/minute",
        "pricing": {"model": "per_call", "cost_units": 2, "currency": "USD"},
        "documentation_url": "https://docs.example.com/search",
        "examples": [
            {
                "method": "GET",
                "endpoint": "/search?q=THE+CLAUDE+COMPANY",
                "description": 'Search for "THE CLAUDE COMPANY"',
            }
        ],
    },
    {
        "api_id": "payments-v1",
        "name": "Payments API",
        "description": "Create charges, refunds, and payouts for marketplace transactions.",
        "category": "payments",
        "version": "3.0.0",
        "endpoint": "https://api.example.com/payments",
        "auth_required": True,
        "rate_limit": "20 requests/minute",
        "pricing": {"model": "percentage", "rate": 0.02, "currency": "USD"},
        "documentation_url": "https://docs.example.com/payments",
        "examples": [
            {
                "method": "POST",
                "endpoint": "/charges",
                "payload": {"amount": 1000, "currency": "usd"},
                "description": "Create a $10.00 charge",
            }
        ],
    },
    {
        "api_id": "public-holidays-v1",
        "name": "Public Holidays API",
        "description": "Public holiday calendar for any country and year.",
        "category": "calendar",
        "version": "1.0.0",
        "endpoint": "https://api.example.com/holidays",
        "auth_required": False,
        "rate_limit": "120 requests/minute",
        "pricing": {"model": "free", "cost_units": 0, "currency": "USD"},
        "documentation_url": "https://docs.example.com/holidays",
        "examples": [
            {
                "method": "GET",
                "endpoint": "/holidays?country=US&year=2026",
                "description": "US public holidays in 2026",
            }
        ],
    },
]


def _ensure_dirs() -> None:
    MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data) -> None:
    _ensure_dirs()
    path.write_text(json.dumps(data, indent=2))


def _load_catalog() -> list:
    catalog = _load_json(CATALOG_FILE, None)
    if not catalog:
        catalog = list(_DEFAULT_CATALOG)
        _save_json(CATALOG_FILE, catalog)
    return catalog


def _load_subscriptions() -> list:
    return _load_json(SUBSCRIPTIONS_FILE, [])


def _save_subscriptions(subscriptions: list) -> None:
    _save_json(SUBSCRIPTIONS_FILE, subscriptions)


def _catalog_entry(api_id: str) -> Optional[dict]:
    for entry in _load_catalog():
        if entry.get("api_id") == api_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_available_apis() -> list:
    """List all available APIs in the marketplace."""
    catalog = _load_catalog()
    public_fields = (
        "api_id",
        "name",
        "description",
        "category",
        "version",
        "endpoint",
        "auth_required",
        "rate_limit",
        "pricing",
    )
    return [{field: entry.get(field) for field in public_fields} for entry in catalog]


def get_api_details(api_id: str) -> Optional[dict]:
    """Get full details for a single API, including documentation and examples."""
    entry = _catalog_entry(api_id)
    if entry is None:
        return None
    return dict(entry)


def subscribe_to_api(workspace_id: str, api_id: str) -> dict:
    """Subscribe a workspace to an API.

    Creates a subscription record and issues an API key the workspace can use
    to invoke the subscribed API.
    """
    if _catalog_entry(api_id) is None:
        raise ValueError(f"Unknown api_id: {api_id!r}")

    subscriptions = _load_subscriptions()
    subscription_id = f"sub-{uuid.uuid4().hex[:12]}"
    api_key = f"mkt_{secrets.token_urlsafe(32)}"
    created_at = datetime.now(timezone.utc).isoformat()

    record = {
        "subscription_id": subscription_id,
        "workspace_id": workspace_id,
        "api_id": api_id,
        "api_key": api_key,
        "created_at": created_at,
        "active": True,
    }
    subscriptions.append(record)
    _save_subscriptions(subscriptions)

    return {
        "subscription_id": subscription_id,
        "workspace_id": workspace_id,
        "api_id": api_id,
        "api_key": api_key,
        "created_at": created_at,
    }


def list_subscriptions(workspace_id: str) -> list:
    """List all API subscriptions for a workspace."""
    subscriptions = _load_subscriptions()
    return [
        {
            "subscription_id": sub.get("subscription_id"),
            "workspace_id": sub.get("workspace_id"),
            "api_id": sub.get("api_id"),
            "api_key": sub.get("api_key"),
            "created_at": sub.get("created_at"),
            "active": sub.get("active", True),
        }
        for sub in subscriptions
        if sub.get("workspace_id") == workspace_id
    ]


def cancel_subscription(subscription_id: str) -> bool:
    """Cancel an API subscription by ID. Returns True if a subscription was removed."""
    subscriptions = _load_subscriptions()
    for index, sub in enumerate(subscriptions):
        if sub.get("subscription_id") == subscription_id:
            subscriptions.pop(index)
            _save_subscriptions(subscriptions)
            return True
    return False


def invoke_api(subscription_id: str, endpoint: str, method: str, payload: dict = None) -> dict:
    """Invoke a subscribed API.

    Simulates an API call against the subscribed API's endpoint. Returns the
    simulated response along with the cost in pricing units.
    """
    subscriptions = _load_subscriptions()
    subscription = None
    for sub in subscriptions:
        if sub.get("subscription_id") == subscription_id:
            subscription = sub
            break

    if subscription is None:
        raise ValueError(f"Unknown subscription_id: {subscription_id!r}")
    if not subscription.get("active", True):
        raise ValueError(f"Subscription {subscription_id!r} is not active")

    api_id = subscription.get("api_id")
    entry = _catalog_entry(api_id)
    if entry is None:
        raise ValueError(f"Subscribed API {api_id!r} is no longer available")

    method = (method or "GET").upper()
    cost_units = entry.get("pricing", {}).get("cost_units", 0)

    response = {
        "api_id": api_id,
        "endpoint": endpoint,
        "method": method,
        "payload": payload,
        "data": {
            "note": "simulated marketplace response",
            "api": entry.get("name"),
        },
    }

    return {
        "subscription_id": subscription_id,
        "endpoint": endpoint,
        "status": "success",
        "response": response,
        "cost_units": cost_units,
    }
