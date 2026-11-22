#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost Chaos Engineering

Chaos engineering utilities for the Dost dispatcher:

* :func:`inject_provider_failure` — temporarily mark a provider as unavailable.
* :func:`run_chaos_test` — run dispatch tests while providers are failing.
* :func:`check_graceful_degradation` — verify the system degrades (falls back)
  instead of crashing when providers fail.

Provider failures are recorded in a module-level registry keyed by provider
name with an expiry time. Dispatch functions can consult :func:`is_provider_failed`
to decide whether to serve a degraded/fallback response rather than crash.

Run: python -m pytest dost/tests/test_chaos.py -q
       python dost/tests/test_chaos.py   # self-check demo
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

__all__ = [
    "inject_provider_failure",
    "is_provider_failed",
    "clear_provider_failure",
    "reset_failures",
    "run_chaos_test",
    "check_graceful_degradation",
]

# provider_name -> expiry timestamp (monotonic clock, seconds)
_FAILED_PROVIDERS: dict[str, float] = {}
_FAILED_PROVIDERS_LOCK = threading.Lock()
# Audit log of every injected failure (for test introspection).
_FAILURE_LOG: list[dict] = []


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def inject_provider_failure(provider_name: str, duration_seconds: int) -> dict:
    """Simulate a provider failure.

    Temporarily marks ``provider_name`` as unavailable for
    ``duration_seconds`` seconds. The failure is registered in a module-level
    expiry table that dispatch functions can poll via :func:`is_provider_failed`
    to decide whether to degrade gracefully.

    Returns:
        {"provider": ..., "duration": ..., "started_at": ...}
    """
    started_at = time.monotonic()
    expiry = started_at + max(0, int(duration_seconds))

    with _FAILED_PROVIDERS_LOCK:
        _FAILED_PROVIDERS[provider_name] = expiry

    record = {
        "provider": provider_name,
        "duration": int(duration_seconds),
        "started_at": _now_iso(),
        "expiry_monotonic": expiry,
    }
    with _FAILED_PROVIDERS_LOCK:
        _FAILURE_LOG.append(dict(record))

    return {
        "provider": provider_name,
        "duration": int(duration_seconds),
        "started_at": record["started_at"],
    }


def is_provider_failed(provider_name: str) -> bool:
    """Return True if ``provider_name`` is currently in an injected failure state.

    Entries whose failure window has elapsed are purged automatically.
    """
    now = time.monotonic()
    with _FAILED_PROVIDERS_LOCK:
        expiry = _FAILED_PROVIDERS.get(provider_name)
    if expiry is None:
        return False
    if now >= expiry:
        with _FAILED_PROVIDERS_LOCK:
            _FAILED_PROVIDERS.pop(provider_name, None)
        return False
    return True


def clear_provider_failure(provider_name: str) -> bool:
    """Manually clear an injected provider failure. Returns True if one was cleared."""
    with _FAILED_PROVIDERS_LOCK:
        return _FAILED_PROVIDERS.pop(provider_name, None) is not None


def reset_failures() -> None:
    """Clear all injected provider failures and the failure log (test hygiene)."""
    with _FAILED_PROVIDERS_LOCK:
        _FAILED_PROVIDERS.clear()
        _FAILURE_LOG.clear()


def _normalize_scenario(scenario) -> tuple[str, int]:
    """Extract ``(provider_name, duration_seconds)`` from a scenario dict or tuple."""
    if isinstance(scenario, dict):
        provider = scenario["provider"]
        duration = scenario.get("duration", scenario.get("duration_seconds", 0))
    elif isinstance(scenario, (tuple, list)) and len(scenario) >= 2:
        provider, duration = scenario[0], scenario[1]
    else:
        raise ValueError(f"Invalid failure scenario: {scenario!r}")
    return str(provider), int(duration)


def run_chaos_test(dispatch_func: Callable, failure_scenarios: list) -> dict:
    """Run dispatch tests during provider failures.

    Iterates over ``failure_scenarios`` (each a dict like
    ``{"provider": ..., "duration": ...}`` or a ``(provider, duration)`` tuple),
    injects the provider failure, then calls ``dispatch_func()``. A test
    "passes" when ``dispatch_func`` returns without raising; it "fails" when
    ``dispatch_func`` raises an exception.

    Returns:
        {"total_tests": ..., "passed": ..., "failed": ..., "results": [...]}
    """
    results: list[dict] = []
    passed = 0
    failed = 0

    for scenario in failure_scenarios:
        provider, duration = _normalize_scenario(scenario)
        inject_provider_failure(provider, duration)

        result = {
            "provider": provider,
            "duration": duration,
            "started_at": _now_iso(),
            "passed": False,
            "error": None,
            "response": None,
        }

        try:
            response = dispatch_func()
            result["response"] = response
            result["passed"] = True
            passed += 1
        except Exception as exc:  # noqa: BLE001 — chaos tests capture any failure
            result["error"] = f"{type(exc).__name__}: {exc}"
            failed += 1

        results.append(result)

    return {
        "total_tests": len(failure_scenarios),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


def _looks_like_degraded_response(response) -> bool:
    """Heuristic: response counts as degraded-but-usable if it carries content."""
    if response is None:
        return False
    if isinstance(response, dict):
        return bool(
            response.get("response")
            or response.get("text")
            or response.get("answer")
            or response.get("content")
        )
    return bool(response)


def check_graceful_degradation(dispatch_func: Callable) -> dict:
    """Test that the system degrades gracefully when providers fail.

    Runs :func:`run_chaos_test` against a small battery of provider failure
    scenarios (groq, openai, local). ``dispatch_func`` is expected to consult
    provider health (e.g. via :func:`is_provider_failed`) and return a
    degraded/fallback response instead of crashing.

    A system is judged to degrade gracefully if ``dispatch_func`` returns a
    usable response in at least one failure scenario — i.e. it has a fallback
    path and does not crash outright under every provider failure.

    Returns:
        {"degraded_gracefully": bool, "details": [...]}
    """
    scenarios = [
        {"provider": "groq", "duration": 5},
        {"provider": "openai", "duration": 5},
        {"provider": "local", "duration": 5},
    ]

    summary = run_chaos_test(dispatch_func, scenarios)

    details = []
    for r in summary["results"]:
        details.append(
            {
                "provider": r["provider"],
                "passed": r["passed"],
                "error": r["error"],
                "response": r["response"],
            }
        )

    # Graceful degradation: kept working (returned a response) under at least
    # one provider failure instead of crashing in every scenario.
    degraded_gracefully = any(r["passed"] and _looks_like_degraded_response(r["response"]) for r in summary["results"])

    return {
        "degraded_gracefully": degraded_gracefully,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Self-check demo (run with: python dost/tests/test_chaos.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    def fake_dispatch():
        """A dispatch function with a fallback path for failed providers."""
        if is_provider_failed("groq") and is_provider_failed("openai"):
            return {"response": "fallback answer", "degraded": True, "provider": "none"}
        if is_provider_failed("groq"):
            return {"response": "openai answer", "provider": "openai"}
        return {"response": "primary answer", "provider": "groq"}

    print("== inject_provider_failure ==")
    print(inject_provider_failure("groq", 5))

    print("== run_chaos_test ==")
    summary = run_chaos_test(
        fake_dispatch,
        [
            {"provider": "groq", "duration": 5},
            {"provider": "openai", "duration": 5},
            {"provider": "nonexistent", "duration": 1},
        ],
    )
    print(
        f"total={summary['total_tests']} passed={summary['passed']} "
        f"failed={summary['failed']}"
    )
    for r in summary["results"]:
        print("  ", r["provider"], "passed=", r["passed"], "error=", r["error"])

    print("== check_graceful_degradation ==")
    print(check_graceful_degradation(fake_dispatch))

    reset_failures()
    print("== done ==")
