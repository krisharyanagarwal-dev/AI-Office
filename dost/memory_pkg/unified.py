"""Unified Memory Layer for Dost.

Single API over:
- jarvis_memory/ (alerts, pending_actions, conversations.jsonl)
- memory_pkg/ (ConversationMemory, persistent_memory)

Provides:
- Session management (load/save per conversation_id)
- Fact extraction (entities, preferences, decisions)
- Vector search (semantic recall via embeddings)
- Cross-interface sync (voice, web, CLI, Telegram)
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _default_paths() -> tuple[Path, Path]:
    """Get default memory directory paths."""
    DOST_DIR = Path(__file__).resolve().parent.parent
    JARVIS_DIR = DOST_DIR / "jarvis_memory"
    MEMORY_DIR = Path(os.path.expanduser("~/.openclaw/dost_memory"))
    JARVIS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return JARVIS_DIR, MEMORY_DIR


@dataclass
class Fact:
    """Extracted fact from conversation."""
    id: str
    type: str  # entity, preference, decision, action_item
    content: str
    confidence: float
    source: str  # voice, web, cli, telegram
    conversation_id: str
    timestamp: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Session:
    """Conversation session."""
    id: str
    interface: str  # voice, web, cli, telegram
    user_id: Optional[str]
    created_at: str
    updated_at: str
    messages: list[dict] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # Cross-interface tracking
    interface_history: list[dict] = field(default_factory=list)  # [{"interface": str, "at": str, "message_count": int}]
    summary: str = ""  # Auto-generated conversation summary
    last_summary_at: str = ""
    context_window: int = 20  # Max messages to keep in context


class UnifiedMemory:
    """Unified memory layer for Dost."""

    def __init__(
        self,
        workspace_id: str = "default",
        jarvis_dir: Path | None = None,
        memory_dir: Path | None = None,
    ):
        self.workspace_id = workspace_id
        self._sessions: dict[str, Session] = {}
        self._facts_cache: list[Fact] = []
        self._vector_index: dict[str, list[float]] = {}

        # Resolve paths
        default_jarvis, default_memory = _default_paths()
        self.jarvis_dir = jarvis_dir or default_jarvis
        self.memory_dir = memory_dir or default_memory

        # Files
        self.conversations_file = self.jarvis_dir / "conversations.jsonl"
        self.pending_actions_file = self.jarvis_dir / "pending_actions.json"
        self.alerts_file = self.jarvis_dir / "alerts.jsonl"
        self.facts_file = self.memory_dir / "facts.json"
        self.vector_index_file = self.memory_dir / "vector_index.json"
        self.preferences_file = self.memory_dir / "preferences.json"

        # Ensure directories and files exist
        self.jarvis_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_file.touch(exist_ok=True)

        self._load_facts()
        self._load_vector_index()

    # ----------------------- Session Management -----------------------

    def create_session(
        self,
        conversation_id: str | None = None,
        interface: str = "cli",
        user_id: str | None = None,
        context_window: int = 20,
    ) -> Session:
        """Create a new conversation session."""
        cid = conversation_id or f"conv-{uuid.uuid4().hex[:8]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        session = Session(
            id=cid,
            interface=interface,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            context_window=context_window,
        )
        self._sessions[cid] = session
        return session

    def get_session(self, conversation_id: str) -> Session | None:
        """Get session by ID."""
        return self._sessions.get(conversation_id)

    def load_session(self, conversation_id: str) -> Session | None:
        """Load session from disk."""
        # Try jarvis_memory conversations.jsonl first
        session = None
        if self.conversations_file.exists():
            for line in self.conversations_file.read_text().strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("conversation_id") == conversation_id:
                        session = Session(
                            id=data["conversation_id"],
                            interface=data.get("interface", "unknown"),
                            user_id=data.get("user_id"),
                            created_at=data.get("created_at", ""),
                            updated_at=data.get("updated_at", ""),
                            messages=data.get("messages", []),
                            metadata=data.get("metadata", {}),
                            interface_history=data.get("interface_history", []),
                            summary=data.get("summary", ""),
                            last_summary_at=data.get("last_summary_at", ""),
                            context_window=data.get("context_window", 20),
                        )
                except json.JSONDecodeError:
                    continue
            if session:
                self._sessions[conversation_id] = session
                return session

        # Fallback to memory_pkg conversations (use instance memory_dir for isolation)
        from memory_pkg.persistent_memory import ConversationMemory
        conv_mem = ConversationMemory(self.workspace_id, memory_dir=self.memory_dir)
        interactions = conv_mem.get_recent_context(limit=50)
        if interactions:
            session = Session(
                id=conversation_id,
                interface="cli",
                user_id=None,
                created_at=interactions[0].get("timestamp", "") if interactions else "",
                updated_at=interactions[-1].get("timestamp", "") if interactions else "",
                messages=[{"role": "user" if i % 2 == 0 else "assistant", "content": msg.get("user_message") or msg.get("dost_response")} for i, msg in enumerate(interactions)],
            )
            self._sessions[conversation_id] = session
            return session

        return None

    def save_session(self, session: Session) -> None:
        """Save session to disk (both stores)."""
        session.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Save to jarvis_memory/conversations.jsonl
        data = {
            "conversation_id": session.id,
            "interface": session.interface,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "messages": session.messages,
            "metadata": session.metadata,
            "interface_history": session.interface_history,
            "summary": session.summary,
            "last_summary_at": session.last_summary_at,
            "context_window": session.context_window,
        }
        # Append to JSONL (one line per session update)
        with open(self.conversations_file, "a") as f:
            f.write(json.dumps(data) + "\n")

        # Also save to memory_pkg
        from memory_pkg.persistent_memory import ConversationMemory
        conv_mem = ConversationMemory(self.workspace_id)
        for i, msg in enumerate(session.messages):
            if msg["role"] == "user":
                conv_mem.add_interaction(
                    user_message=msg["content"],
                    dost_response=session.messages[i + 1].get("content", "") if i + 1 < len(session.messages) else "",
                    metadata={"session_id": session.id, "interface": session.interface},
                )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> Session:
        """Add a message to a session."""
        session = self._sessions.get(conversation_id)
        if not session:
            session = self.load_session(conversation_id)
        if not session:
            session = self.create_session(conversation_id)

        session.messages.append({
            "role": role,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata": metadata or {},
        })
        self.save_session(session)
        return session

    def record_turn(
        self,
        conversation_id: str,
        interface: str,
        user_message: str,
        dost_response: str,
    ) -> Session:
        """Persist one complete turn without duplicating legacy interactions."""
        session = self._sessions.get(conversation_id) or self.load_session(conversation_id)
        if not session:
            session = self.create_session(conversation_id, interface=interface)
        elif session.interface != interface:
            session.interface_history.append({
                "from_interface": session.interface,
                "to_interface": interface,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "message_count": len(session.messages),
            })
        session.interface = interface

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        session.messages.extend([
            {
                "role": "user",
                "content": user_message,
                "timestamp": now,
                "metadata": {"source_interface": interface},
            },
            {
                "role": "assistant",
                "content": dost_response,
                "timestamp": now,
                "metadata": {"source_interface": interface},
            },
        ])
        session.updated_at = now

        data = {
            "conversation_id": session.id,
            "interface": session.interface,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "messages": session.messages,
            "metadata": session.metadata,
            "interface_history": session.interface_history,
            "summary": session.summary,
            "last_summary_at": session.last_summary_at,
            "context_window": session.context_window,
        }
        with open(self.conversations_file, "a") as f:
            f.write(json.dumps(data) + "\n")

        from memory_pkg.persistent_memory import ConversationMemory
        ConversationMemory(self.workspace_id, memory_dir=self.memory_dir).add_interaction(
            user_message=user_message,
            dost_response=dost_response,
            metadata={"session_id": session.id, "interface": interface},
        )
        self.extract_facts(user_message, conversation_id, interface)
        return session

    def get_context(self, conversation_id: str, limit: int = 10) -> list[dict]:
        """Get recent conversation context for LLM."""
        session = self._sessions.get(conversation_id) or self.load_session(conversation_id)
        if not session:
            return []
        return session.messages[-limit:]

    # ----------------------- Fact Extraction -----------------------

    def _load_facts(self) -> None:
        """Load facts from disk."""
        if self.facts_file.exists():
            try:
                data = json.loads(self.facts_file.read_text())
                self._facts_cache = [Fact(**f) for f in data]
            except (json.JSONDecodeError, TypeError):
                self._facts_cache = []

    def _save_facts(self) -> None:
        """Save facts to disk."""
        self.facts_file.write_text(json.dumps([f.__dict__ for f in self._facts_cache], indent=2))

    def extract_facts(self, text: str, conversation_id: str, source: str) -> list[Fact]:
        """Extract facts from text using simple patterns."""
        facts = []
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Entity patterns (capitalized words, tickers, etc.)
        entities = re.findall(r'\b[A-Z]{2,5}\b|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        for entity in set(entities):
            if len(entity) > 2:
                fact = Fact(
                    id=f"fact-{uuid.uuid4().hex[:8]}",
                    type="entity",
                    content=entity,
                    confidence=0.9,
                    source=source,
                    conversation_id=conversation_id,
                    timestamp=now,
                    metadata={"extracted_from": text[:100]},
                )
                facts.append(fact)

        # Preference patterns
        pref_patterns = [
            (r"(?:i prefer|i like|i want|my preference is)\s+([^.]+)", "preference"),
            (r"(?:always|never)\s+([^.]+)", "preference"),
            # Additional preference patterns
            (r"(?:i don't want|i dont want)\s+([^.]+)", "preference"),
            (r"(?:i plan to)\s+([^.]+)", "decision"),
            (r"(?:i must)\s+([^.]+)", "decision"),
        ]
        pref_confidences = [0.8, 0.8, 0.85, 0.85, 0.9]
        for i, (pattern, ftype) in enumerate(pref_patterns):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                fact = Fact(
                    id=f"fact-{uuid.uuid4().hex[:8]}",
                    type=ftype,
                    content=match.group(1).strip(),
                    confidence=pref_confidences[i],
                    source=source,
                    conversation_id=conversation_id,
                    timestamp=now,
                )
                facts.append(fact)

        # Decision patterns
        decision_patterns = [
            (r"(?:decided to|decided|will|going to)\s+([^.]+)", "decision"),
        ]
        for pattern, ftype in decision_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                fact = Fact(
                    id=f"fact-{uuid.uuid4().hex[:8]}",
                    type=ftype,
                    content=match.group(1).strip(),
                    confidence=0.75,
                    source=source,
                    conversation_id=conversation_id,
                    timestamp=now,
                )
                facts.append(fact)

        # Action items
        action_patterns = [
            (r"(?:need to|have to|should|must|todo:|action:)\s+(.+?)(?:\.|!|\?|$)", "action_item"),
        ]
        for pattern, ftype in action_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                fact = Fact(
                    id=f"fact-{uuid.uuid4().hex[:8]}",
                    type=ftype,
                    content=match.group(1).strip(),
                    confidence=0.8,
                    source=source,
                    conversation_id=conversation_id,
                    timestamp=now,
                )
                facts.append(fact)

        # Add to cache, vector index, and save
        for fact in facts:
            self._facts_cache.append(fact)
            self.add_to_index(fact)
        self._save_facts()

        return facts

    def get_facts(
        self,
        conversation_id: str | None = None,
        fact_type: str | None = None,
        limit: int = 50,
    ) -> list[Fact]:
        """Get facts, optionally filtered."""
        facts = self._facts_cache
        if conversation_id:
            facts = [f for f in facts if f.conversation_id == conversation_id]
        if fact_type:
            facts = [f for f in facts if f.type == fact_type]
        return facts[-limit:]

    # ----------------------- Vector Search -----------------------

    def _load_vector_index(self) -> None:
        """Load vector index from disk."""
        if self.vector_index_file.exists():
            try:
                self._vector_index = json.loads(self.vector_index_file.read_text())
            except json.JSONDecodeError:
                self._vector_index = {}

    def _save_vector_index(self) -> None:
        """Save vector index to disk."""
        self.vector_index_file.write_text(json.dumps(self._vector_index))

    def _get_embedding(self, text: str) -> list[float]:
        """Get embedding for text (placeholder - use real embedding model)."""
        # Simple hash-based embedding for now
        import hashlib
        hash_bytes = hashlib.md5(text.encode()).digest()
        return [b / 255.0 for b in hash_bytes[:16]]  # 16-dim

    def add_to_index(self, fact: Fact) -> None:
        """Add fact to vector index."""
        embedding = self._get_embedding(fact.content)
        self._vector_index[fact.id] = embedding
        self._save_vector_index()

    def search(self, query: str, limit: int = 10) -> list[Fact]:
        """Semantic search for relevant facts."""
        if not self._vector_index or not self._facts_cache:
            return []

        query_emb = self._get_embedding(query)

        # Cosine similarity
        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(y * y for y in b) ** 0.5
            return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0

        scored = []
        for fact in self._facts_cache:
            if fact.id in self._vector_index:
                sim = cosine_sim(query_emb, self._vector_index[fact.id])
                scored.append((sim, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:limit]]

    # ----------------------- Preferences -----------------------

    def _load_preferences(self) -> dict:
        if self.preferences_file.exists():
            try:
                return json.loads(self.preferences_file.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_preferences(self, prefs: dict) -> None:
        self.preferences_file.write_text(json.dumps(prefs, indent=2))

    def set_preference(self, key: str, value: Any) -> None:
        prefs = self._load_preferences()
        prefs[key] = value
        self._save_preferences(prefs)

    def get_preference(self, key: str, default: Any = None) -> Any:
        prefs = self._load_preferences()
        return prefs.get(key, default)

    # ----------------------- Cross-Interface Sync -----------------------

    def sync_from_interface(
        self,
        conversation_id: str,
        interface: str,
        messages: list[dict],
    ) -> Session:
        """Sync messages from an interface (voice, web, cli, telegram)."""
        session = self.load_session(conversation_id)
        if not session:
            session = self.create_session(conversation_id, interface=interface)
        else:
            # Track interface switch
            prev_interface = session.interface
            if prev_interface != interface:
                session.interface_history.append({
                    "from_interface": prev_interface,
                    "to_interface": interface,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "message_count": len(session.messages),
                })
            session.interface = interface

        for msg in messages:
            self.add_message(
                conversation_id,
                msg["role"],
                msg["content"],
                {"source_interface": interface, **msg.get("metadata", {})},
            )

        # Extract facts from new messages
        for msg in messages:
            self.extract_facts(msg["content"], conversation_id, interface)

        return self._sessions[conversation_id]

    def get_all_context(self, conversation_id: str, limit: int = 20) -> dict:
        """Get complete context for a conversation (for LLM)."""
        session = self._sessions.get(conversation_id) or self.load_session(conversation_id)
        if not session:
            return {"messages": [], "facts": [], "preferences": self._load_preferences()}

        return {
            "messages": session.messages[-limit:],
            "facts": [f.__dict__ for f in self.get_facts(conversation_id)],
            "preferences": self._load_preferences(),
            "summary": session.summary,
            "interface_history": session.interface_history,
        }

    def build_context_prompt(self, conversation_id: str, current_query: str, limit: int = 20) -> str:
        """Build context-aware prompt with memory injection for LLM.

        Injects:
        - Conversation summary
        - Recent messages
        - Relevant facts (entities, preferences, decisions)
        - Interface context
        """
        context = self.get_all_context(conversation_id, limit=limit)
        session = self._sessions.get(conversation_id) or self.load_session(conversation_id)

        if not session or not session.messages:
            return current_query

        parts = []

        # 1. Conversation summary
        if session.summary:
            parts.append(f"=== Conversation Summary ===\n{session.summary}\n")

        # 2. Relevant facts
        facts = self.search(current_query, limit=5)
        if facts:
            fact_lines = [f"- {f.type}: {f.content} (confidence: {f.confidence:.0%})" for f in facts]
            parts.append("=== Relevant Facts ===\n" + "\n".join(fact_lines) + "\n")

        # 3. User preferences
        prefs = context.get("preferences", {})
        if prefs:
            pref_lines = [f"- {k}: {v}" for k, v in prefs.items()]
            parts.append("=== User Preferences ===\n" + "\n".join(pref_lines) + "\n")

        # 4. Recent conversation
        recent_msgs = context.get("messages", [])
        if recent_msgs:
            msg_lines = []
            for msg in recent_msgs[-10:]:  # Last 10 messages
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:200]
                src = msg.get("metadata", {}).get("source_interface", "")
                src_tag = f" [{src}]" if src else ""
                msg_lines.append(f"{role}{src_tag}: {content}")
            parts.append("=== Recent Conversation ===\n" + "\n".join(msg_lines) + "\n")

        # 5. Current query
        parts.append(f"=== Current Query ===\n{current_query}")

        return "\n".join(parts)

    def summarize_session(self, conversation_id: str) -> str:
        """Generate conversation summary using LLM (or simple extraction)."""
        session = self._sessions.get(conversation_id) or self.load_session(conversation_id)
        if not session or not session.messages:
            return ""

        # Extract key topics from messages
        all_text = " ".join(m.get("content", "") for m in session.messages)

        # Simple extractive summary: top entities, decisions, action items
        entities = self.get_facts(conversation_id, fact_type="entity", limit=10)
        decisions = self.get_facts(conversation_id, fact_type="decision", limit=5)
        actions = self.get_facts(conversation_id, fact_type="action_item", limit=5)
        prefs = self.get_facts(conversation_id, fact_type="preference", limit=5)

        summary_parts = []
        if entities:
            summary_parts.append(f"Entities discussed: {', '.join(e.content for e in entities[:5])}")
        if decisions:
            summary_parts.append(f"Decisions: {'; '.join(d.content for d in decisions[:3])}")
        if actions:
            summary_parts.append(f"Action items: {'; '.join(a.content for a in actions[:3])}")
        if prefs:
            summary_parts.append(f"Preferences noted: {'; '.join(p.content for p in prefs[:3])}")

        summary = ". ".join(summary_parts)

        # Update session
        session.summary = summary
        session.last_summary_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.save_session(session)

        return summary

    def merge_sessions(self, primary_id: str, secondary_id: str) -> Session:
        """Merge secondary session into primary (for cross-interface continuity)."""
        primary = self._sessions.get(primary_id) or self.load_session(primary_id)
        secondary = self._sessions.get(secondary_id) or self.load_session(secondary_id)

        if not primary or not secondary:
            raise ValueError("Both sessions must exist")

        # Merge messages chronologically
        all_messages = primary.messages + secondary.messages
        all_messages.sort(key=lambda m: m.get("timestamp", ""))

        # Keep within context window
        if len(all_messages) > primary.context_window:
            all_messages = all_messages[-primary.context_window:]

        primary.messages = all_messages
        primary.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Add secondary's initial interface as a history entry if not already present
        if secondary.interface and (not primary.interface_history or primary.interface_history[-1].get("to_interface") != secondary.interface):
            primary.interface_history.append({
                "from_interface": primary.interface,
                "to_interface": secondary.interface,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "message_count": len(primary.messages),
            })
        primary.interface_history.extend(secondary.interface_history)

        # Merge facts
        for fact in secondary.facts:
            if fact not in primary.facts:
                primary.facts.append(fact)

        self.save_session(primary)
        return primary

    def get_session_stats(self, conversation_id: str) -> dict:
        """Get statistics for a session."""
        session = self._sessions.get(conversation_id) or self.load_session(conversation_id)
        if not session:
            return {}

        interfaces = set(m.get("metadata", {}).get("source_interface", "") for m in session.messages)
        interfaces.discard("")

        return {
            "conversation_id": session.id,
            "message_count": len(session.messages),
            "fact_count": len(self.get_facts(conversation_id)),
            "interfaces_used": list(interfaces),
            "interface_switches": len(session.interface_history),
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "has_summary": bool(session.summary),
            "context_window": session.context_window,
        }


# Global instances per workspace
_unified_memories: dict[str, UnifiedMemory] = {}


def get_unified_memory(workspace_id: str = "default") -> UnifiedMemory:
    """Get global unified memory instance for workspace."""
    global _unified_memories
    if workspace_id not in _unified_memories:
        _unified_memories[workspace_id] = UnifiedMemory(workspace_id)
    return _unified_memories[workspace_id]