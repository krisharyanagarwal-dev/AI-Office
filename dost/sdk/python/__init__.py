"""Dost Python SDK for THE CLAUDE COMPANY API."""

from .client import DostAPIError, DostClient, DostError
from .models import Debate, Finding, Task, Workspace

__all__ = [
    "DostClient",
    "DostAPIError",
    "DostError",
    "Task",
    "Finding",
    "Debate",
    "Workspace",
]

__version__ = "0.1.0"
