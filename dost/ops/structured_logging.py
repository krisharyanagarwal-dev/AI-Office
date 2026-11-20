"""
Structured logging for THE CLAUDE COMPANY dispatcher.

Provides structured JSON logging for dispatch events, debate events,
and system events. All logs are written in JSON format for easy
parsing by log aggregation systems.
"""

import json
import logging
import sys
import time
import uuid
from typing import Any, Dict, Optional

_LOGGER_CONFIGURED = False


def _setup_logging(log_level: str = "INFO", log_file: str = None) -> None:
    """Configure structured logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
    """
    global _LOGGER_CONFIGURED

    if _LOGGER_CONFIGURED:
        return

    logger = logging.getLogger("dost")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter("%(message)s")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _LOGGER_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        logging.Logger instance
    """
    return logging.getLogger(f"dost.{name}")


def log_event(event_type: str, message: str, level: str = "INFO", **kwargs) -> None:
    """Log a structured event.

    Args:
        event_type: Type of event (dispatch, debate, finding, etc.)
        message: Human-readable message
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        **kwargs: Additional structured fields
    """
    logger = logging.getLogger("dost")
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": event_type,
        "message": message,
        "level": level,
        **kwargs
    }
    logger.log(getattr(logging, level.upper(), logging.INFO), json.dumps(log_event))


def log_dispatch(task_id: str, agent_id: str, status: str, duration_ms: float,
                 cost_units: int = 0, error: str = None) -> None:
    """Log a dispatch event.

    Args:
        task_id: Task ID
        agent_id: Agent ID
        status: Task status (pending, done, error)
        duration_ms: Execution duration in milliseconds
        cost_units: Cost units consumed
        error: Error message if failed
    """
    log_event(
        event_type="dispatch",
        message=f"Dispatched task {task_id} to {agent_id}: {status}",
        level="INFO" if status == "done" else "ERROR",
        task_id=task_id,
        agent_id=agent_id,
        status=status,
        duration_ms=duration_ms,
        cost_units=cost_units,
        error=error,
    )


def log_debate(debate_id: str, agent_id: str, answer_length: int,
               error: str = None) -> None:
    """Log a debate event.

    Args:
        debate_id: Debate ID
        agent_id: Agent ID
        answer_length: Length of agent's answer
        error: Error message if failed
    """
    log_event(
        event_type="debate",
        message=f"Debate agent {agent_id} answered",
        level="INFO" if not error else "ERROR",
        debate_id=debate_id,
        agent_id=agent_id,
        answer_length=answer_length,
        error=error,
    )