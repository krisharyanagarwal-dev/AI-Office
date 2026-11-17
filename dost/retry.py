"""
Retry with exponential backoff for THE CLAUDE COMPANY dispatcher.

Provides retry logic with exponential backoff for handling transient
failures when calling provider APIs.
"""

import time
import random
from typing import Callable, Any, Optional, Tuple, Type


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, message: str, last_exception: Exception = None):
        super().__init__(message)
        self.last_exception = last_exception


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
) -> Any:
    """
    Retry a function with exponential backoff.

    Args:
        func: Function to call
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for exponential backoff
        retryable_exceptions: Tuple of exception types to retry on

    Returns:
        Function result on success

    Raises:
        RetryExhaustedError: If all retries are exhausted
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                # Add jitter
                delay = delay * (0.5 + random.random() * 0.5)
                time.sleep(delay)

    raise RetryExhaustedError(
        f"Failed after {max_retries + 1} attempts: {last_exception}",
        last_exception
    )


def retry_sync(func: Callable, *args, max_retries: int = 3, **kwargs) -> Any:
    """Synchronous retry wrapper.

    Convenience wrapper around retry_with_backoff for synchronous functions.
    """
    return retry_with_backoff(lambda: func(*args, **kwargs),
                              max_retries=max_retries)


async def retry_async(func: Callable, *args, max_retries: int = 3, **kwargs) -> Any:
    """Async retry wrapper.

    Convenience wrapper around retry_with_backoff for async functions.
    """
    import asyncio

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries:
                delay = min(max_retries * (2 ** attempt), 60.0)
                delay = delay * (0.5 + 0.5 * 0.5)  # jitter
                await asyncio.sleep(delay)
            else:
                raise RetryExhaustedError(
                    f"Failed after {max_retries + 1} attempts: {e}", e
                )

    raise RetryExhaustedError(f"Failed after {max_retries + 1} attempts: {e}")