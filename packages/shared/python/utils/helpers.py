"""
Common helper functions.
"""

import uuid
import re
import time
import functools
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from datetime import timedelta

T = TypeVar('T')


def generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix."""
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}{uid}" if prefix else uid


def slugify(text: str, max_length: int = 50) -> str:
    """Convert text to URL-safe slug."""
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    # Truncate
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip('-')
    return slug


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse human-readable duration string (e.g., '1h30m', '5m', '2h')."""
    pattern = r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    match = re.fullmatch(pattern, text.strip().lower())
    if not match:
        return None
    
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    
    if hours == 0 and minutes == 0 and seconds == 0:
        return None
    
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def format_duration(td: timedelta) -> str:
    """Format timedelta as human-readable string."""
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    
    return "".join(parts)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def flatten_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """Flatten a nested dictionary using dot notation."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator for retrying a function with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts
        delay: Initial delay in seconds
        backoff: Multiplier for delay after each attempt
        exceptions: Exception types to catch
        on_retry: Optional callback(exception, attempt) called on each retry
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(e, attempt)
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise
            
            # This should never be reached, but just in case
            raise last_exception
        
        return wrapper
    return decorator


async def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], Any]] = None,
):
    """
    Async decorator for retrying a function with exponential backoff.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        if on_retry:
                            await on_retry(e, attempt)
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise
            
            raise last_exception
        
        return wrapper
    return decorator


import asyncio