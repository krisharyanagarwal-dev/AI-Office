"""
Structured JSON logging with daily rotation and service identification.
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def __init__(self, service_name: str = "ai-office", **kwargs):
        super().__init__(**kwargs)
        self.service_name = service_name
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": getattr(record, "service", self.service_name),
            "message": record.getMessage(),
            "fields": {}
        }
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "name", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info", "service", "taskName",
            }:
                log_entry["fields"][key] = value
        
        # Add exception info if present
        if record.exc_info:
            log_entry["fields"]["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


class StructuredLogger:
    """Wrapper for structured logging with context."""
    
    def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.context = context or {}
    
    def _log(self, level: int, message: str, **kwargs):
        extra = {**self.context, **kwargs}
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)
    
    def with_context(self, **context) -> "StructuredLogger":
        """Create a new logger with additional context."""
        return StructuredLogger(self.logger, {**self.context, **context})


def setup_json_logging(
    service_name: str,
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    console: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 30,
) -> logging.Logger:
    """
    Setup structured JSON logging for a service with rotation.
    
    Args:
        service_name: Name of the service (used in log entries and filename)
        log_dir: Directory for log files (default: ~/AI-Office/logs)
        level: Logging level
        console: Whether to also log to console
        max_bytes: Max size per log file before rotation
        backup_count: Number of rotated files to keep
    
    Returns:
        Configured logger instance
    """
    if log_dir is None:
        log_dir = Path.home() / "AI-Office" / "logs"
    
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{service_name}.log"
    
    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    logger.handlers.clear()
    
    formatter = JSONFormatter(service_name)
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    logger.propagate = False
    return logger


# Global logger cache
_loggers: Dict[str, logging.Logger] = {}


def get_logger(service_name: str, log_dir: Optional[Path] = None, 
               level: int = logging.INFO) -> StructuredLogger:
    """Get or create a structured logger for a service."""
    if service_name not in _loggers:
        _loggers[service_name] = setup_json_logging(service_name, log_dir, level)
    return StructuredLogger(_loggers[service_name])


def get_raw_logger(service_name: str, log_dir: Optional[Path] = None,
                   level: int = logging.INFO) -> logging.Logger:
    """Get the raw logging.Logger instance."""
    if service_name not in _loggers:
        _loggers[service_name] = setup_json_logging(service_name, log_dir, level)
    return _loggers[service_name]