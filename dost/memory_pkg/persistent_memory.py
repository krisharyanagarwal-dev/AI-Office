"""
Persistent Conversation Memory for Dost.

Maintains conversation context across dost invocations so the AI chief of staff
remembers what was discussed, what decisions were made, and what follow-ups
are pending. This enables true multi-session conversations where Dost
remembers context between invocations.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

MEMORY_DIR = Path(os.path.expanduser("~/.openclaw/dost_memory"))
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

CONVERSATIONS_FILE = MEMORY_DIR / "conversations.json"
PENDING_ITEMS_FILE = MEMORY_DIR / "pending_items.json"
USER_PREFERENCES_FILE = MEMORY_DIR / "user_preferences.json"


def _load_json(path: Path, default: Any) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data: Any) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class ConversationMemory:
    """Persistent conversation memory for Dost."""

    def __init__(self, workspace_id: str = "default"):
        self.workspace_id = workspace_id
        self.conversations_file = MEMORY_DIR / f"conversations_{workspace_id}.json"
        self.pending_items_file = MEMORY_DIR / f"pending_items_{workspace_id}.json"
        self.preferences_file = MEMORY_DIR / f"preferences_{workspace_id}.json"

    def add_interaction(
        self,
        user_message: str,
        dost_response: str,
        context: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Add an interaction to conversation history.

        Returns the interaction ID.
        """
        conversations = _load_json(self.conversations_file, [])
        interaction = {
            "id": f"conv-{uuid.uuid4().hex[:8]}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "user_message": user_message,
            "dost_response": dost_response,
            "context": context or {},
            "metadata": metadata or {},
        }
        conversations.append(interaction)
        # Keep only last 50 interactions to keep file size manageable
        conversations = conversations[-50:]
        _save_json(self.conversations_file, conversations)
        return interaction["id"]

    def get_recent_context(self, limit: int = 5) -> list[dict]:
        """Get recent conversation history for context."""
        conversations = _load_json(self.conversations_file, [])
        return conversations[-limit:]

    def get_last_interaction(self) -> Optional[dict]:
        """Get the most recent interaction."""
        conversations = _load_json(self.conversations_file, [])
        if conversations:
            return conversations[-1]
        return None

    def add_pending_item(
        self,
        description: str,
        category: str = "general",
        priority: str = "medium",
        due_date: Optional[str] = None,
        related_task_id: Optional[str] = None,
    ) -> str:
        """Add a pending item that needs follow-up.

        Returns the item ID.
        """
        items = _load_json(self.pending_items_file, [])
        item = {
            "id": f"item-{uuid.uuid4().hex[:8]}",
            "description": description,
            "category": category,
            "priority": priority,  # low, medium, high, critical
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "due_date": due_date,
            "related_task_id": related_task_id,
        }
        items.append(item)
        _save_json(self.pending_items_file, items)
        return item["id"]

    def get_pending_items(self) -> list[dict]:
        """Get all pending items."""
        items = _load_json(self.pending_items_file, [])
        return [item for item in items if item.get("status") == "pending"]

    def mark_item_done(self, item_id: str) -> bool:
        """Mark a pending item as done."""
        items = _load_json(self.pending_items_file, [])
        for item in items:
            if item.get("id") == item_id:
                item["status"] = "done"
                item["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                _save_json(self.pending_items_file, items)
                return True
        return False

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        prefs = _load_json(self.preferences_file, {})
        return prefs.get(key, default)

    def set_preference(self, key: str, value: Any) -> None:
        """Set a user preference."""
        prefs = _load_json(self.preferences_file, {})
        prefs[key] = value
        _save_json(self.preferences_file, prefs)

    def get_context_summary(self) -> str:
        """Generate a summary of recent context for injection into prompts."""
        conversations = _load_json(self.conversations_file, [])
        pending = self.get_pending_items()

        parts = []
        if conversations:
            parts.append("Recent conversation context:")
            for conv in conversations[-3:]:
                parts.append(f"  User: {conv.get('user_message', '')[:100]}")
                parts.append(f"  Dost: {conv.get('dost_response', '')[:100]}")

        if pending:
            parts.append("\nPending items:")
            for item in pending[:5]:
                parts.append(f"  - [{item['priority']}] {item['description']}")

        return "\n".join(parts) if parts else ""


# Global instance
conversation_memory = ConversationMemory()


if __name__ == "__main__":
    cm = ConversationMemory()
    print("Recent context:")
    print(cm.get_context_summary())
    print(f"\nPending items: {len(cm.get_pending_items())}")
    for item in cm.get_pending_items():
        print(f"  [{item['priority']}] {item['description']}")