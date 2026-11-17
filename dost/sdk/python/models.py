"""Data models for the Dost Python SDK.

Represents the core resources exposed by THE CLAUDE COMPANY Dost API:
Task, Finding, Debate and Workspace.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Task:
    """A task dispatched to the Dost fleet for execution by an agent."""

    id: Optional[str] = None
    prompt: str = ""
    agent_id: Optional[str] = None
    status: str = "pending"
    priority: str = "normal"
    parent_task_id: Optional[str] = None
    result: Any = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    workspace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class Finding:
    """An observation produced during task execution or analysis."""

    id: Optional[str] = None
    task_id: Optional[str] = None
    type: str = ""
    severity: str = "info"
    description: str = ""
    evidence: Any = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Finding":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class Debate:
    """A multi-agent debate started on a prompt."""

    id: Optional[str] = None
    prompt: str = ""
    agents: List[str] = field(default_factory=list)
    status: str = "pending"
    winner: Optional[str] = None
    rounds: int = 0
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Debate":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class Workspace:
    """A logical grouping of tasks and findings."""

    id: Optional[str] = None
    name: str = ""
    description: str = ""
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workspace":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})
