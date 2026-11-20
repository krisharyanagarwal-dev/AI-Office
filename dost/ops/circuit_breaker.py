"""
Circuit breaker for THE CLAUDE COMPANY dispatcher.

Prevents cascading failures by tracking provider health and automatically
opening the circuit when failures exceed a threshold.
"""

import time
from typing import Dict, Optional


class CircuitBreaker:
    """Circuit breaker for individual providers."""

    def __init__(self, name: str, failure_threshold: int = 5,
                 reset_timeout: int = 60, half_open_max_calls: int = 3):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = "closed"  # closed, open, half_open
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change = time.time()

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        now = time.time()

        if self.state == "closed":
            return True

        if self.state == "open":
            if now - self.last_failure_time >= self.reset_timeout:
                self.state = "half_open"
                self.success_count = 0
                return True
            return False

        if self.state == "half_open":
            if self.success_count < self.half_open_max_calls:
                return True
            return False

        return False

    def record_success(self):
        """Record a successful call."""
        if self.state == "half_open":
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = "closed"
                self.failure_count = 0
        elif self.state == "closed":
            self.failure_count = 0

    def record_failure(self):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == "half_open":
            self.state = "open"
            self.last_failure_time = time.time()
        elif self.failure_count >= self.failure_threshold:
            self.state = "open"
            self.last_failure_time = time.time()

    def get_state(self) -> str:
        """Get current circuit breaker state."""
        return self.state


class CircuitBreakerRegistry:
    """Registry of circuit breakers."""

    def __init__(self):
        self._breakers: dict = {}

    def get_or_create(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name)
        return self._breakers[name]

    def get_all_states(self) -> dict:
        """Get all circuit breaker states."""
        return {name: cb.get_state() for name, cb in self._breakers.items()}


# Global circuit breaker registry
circuit_breaker_registry = CircuitBreakerRegistry()