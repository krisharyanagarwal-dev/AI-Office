"""
Datetime utilities for consistent timestamp handling.
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Get current UTC datetime with timezone info."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """Get current UTC time as ISO 8601 string with Z suffix."""
    return utc_now().isoformat().replace('+00:00', 'Z')


def parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse ISO 8601 datetime string, handling Z suffix."""
    if not value:
        return None
    # Replace Z with +00:00 for fromisoformat
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    """Format datetime as string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(fmt)


def to_timestamp(dt: datetime) -> float:
    """Convert datetime to Unix timestamp."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def from_timestamp(ts: float) -> datetime:
    """Convert Unix timestamp to UTC datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def is_expired(dt: datetime, ttl_seconds: int) -> bool:
    """Check if a datetime has expired based on TTL."""
    return (utc_now() - dt).total_seconds() > ttl_seconds


def time_until(dt: datetime) -> Optional[float]:
    """Get seconds until a future datetime (None if in past)."""
    diff = (dt - utc_now()).total_seconds()
    return diff if diff > 0 else None