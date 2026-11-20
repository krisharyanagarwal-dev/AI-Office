"""
Regression test for the autopilot's silent hang (found 2026-11-21).

ProviderRouter._lock was a plain threading.Lock, and select_provider() holds it
while calling is_available() and _round_robin_model(), which re-acquire it. On the
same thread that is a self-deadlock: no exception, no log line, no child process,
no socket. Every autopilot round hung on its first model call — 10 rounds started,
0 finished, 0 failed, across 5 days — and the only visible symptom was a missing
round file.

These tests fail by HANGING if the lock ever goes back to a non-reentrant Lock, so
each call is run on a watchdog thread with a hard timeout rather than inline.
"""
import threading

import pytest

from core.router import ProviderRouter

TIMEOUT_SEC = 10


def _call_with_watchdog(fn, *args, **kwargs):
    """Run fn on a thread; fail the test if it does not return in TIMEOUT_SEC."""
    box = {}

    def run():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # a raised error is a result, not a hang
            box["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=TIMEOUT_SEC)
    if t.is_alive():
        pytest.fail(
            f"{getattr(fn, '__name__', fn)} did not return within {TIMEOUT_SEC}s - "
            "the router lock is deadlocking again (threading.Lock instead of RLock?)"
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


@pytest.fixture
def router(monkeypatch):
    r = ProviderRouter()
    # Never touch the real router_state.json from a test.
    monkeypatch.setattr(r, "_save_task_counts", lambda: None)
    return r


def test_lock_is_reentrant(router):
    assert isinstance(router._lock, type(threading.RLock())), (
        "ProviderRouter._lock must be an RLock: select_provider() re-acquires it"
    )


def test_select_provider_returns_and_does_not_deadlock(router):
    pool, model = _call_with_watchdog(router.select_provider, tier="pro")
    assert pool in router.pools, f"unexpected pool {pool!r}"
    assert model, "a selected pool must come with a model"


def test_select_provider_with_preferred_pool_does_not_deadlock(router):
    name = next(iter(router.pools))
    pool, model = _call_with_watchdog(router.select_provider, tier="pro", preferred_pool=name)
    assert pool is not None and model


@pytest.mark.parametrize("tier", ["pro", "general", "lite"])
def test_every_configured_tier_can_be_served(router, tier):
    """A tier no pool serves would make its agents silently unanswerable."""
    pool, model = _call_with_watchdog(router.select_provider, tier=tier)
    assert pool is not None, f"no pool serves tier {tier!r}"


def test_status_does_not_deadlock(router):
    assert _call_with_watchdog(router.status) is not None


def test_mark_then_select_does_not_deadlock(router):
    """The real autopilot path: a failed call cools a pool down, then reselects."""
    name = next(iter(router.pools))
    _call_with_watchdog(router.mark_rate_limited, name)
    _call_with_watchdog(router.select_provider, tier="pro")
    _call_with_watchdog(router.mark_success, name)


def test_concurrent_selection_does_not_deadlock(router):
    """autopilot asks parallel_agents=3 specialists at once through one router."""
    errors = []

    def worker():
        try:
            for _ in range(5):
                router.select_provider(tier="pro")
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=TIMEOUT_SEC)
    alive = [t for t in threads if t.is_alive()]
    assert not alive, f"{len(alive)}/3 concurrent selector threads hung"
    assert not errors, f"concurrent selection raised: {errors[0]!r}"
