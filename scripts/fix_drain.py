import pathlib

p = pathlib.Path("services/free_harness_server.py")
s = p.read_text(encoding="utf-8")

# The wedge mechanism, precisely.
#
# chat_completions wraps harness.call_model in asyncio.wait_for(..., timeout=180).
# call_model runs in a worker thread via asyncio.to_thread. When wait_for expires
# it cancels the *await* -- it cannot kill the thread. The thread keeps running,
# still holding the semaphore slot it acquired inside call_model, and only
# releases it when it finally reaches the release_slot() in its own `finally`.
#
# With OLLAMA_MAX_CONCURRENCY=5 and 57 agents, five abandoned-but-running
# threads hold every ollama slot. Every subsequent request blocks in
# acquire_slot for OLLAMA_SEMAPHORE_TIMEOUT=30s and is then refused as
# queue_saturation, so the client sees "fetch failed" while /health -- which
# never takes a slot -- answers in 3ms. That is the observed state exactly, and
# it is self-sustaining: each new timeout abandons more threads.
#
# My 45s attempt timeout made it worse. It shortened how long a thread is
# abandoned (45s instead of 180s) while simultaneously raising the rate at which
# requests time out and abandon threads, so slots churned rather than draining.
#
# The fix: on timeout, release the abandoned request's slots rather than
# waiting for its thread to notice. acquire_slot is keyed by provider, and
# release_slot is idempotent (it swallows the over-release ValueError), so
# draining the slots the timed-out work was holding unblocks the queue
# immediately. The abandoned thread will hit its own release_slot later and
# that call is a safe no-op.
#
# This is a stopgap, not a cure: the real fix is not abandoning threads at all
# (a cooperative cancellation flag, or moving the provider call to a properly
# cancellable client). It is scoped to unwedge the fleet now, and the drain is
# logged so a leak is visible instead of silent.

OLD = '''    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Provider timeout after {REQUEST_TIMEOUT:g}s",
        )'''

NEW = '''    except asyncio.TimeoutError:
        # The worker thread cannot be cancelled -- asyncio.wait_for only
        # abandons the await -- so it is still running and still holding the
        # provider slots it acquired. With a small local concurrency limit and
        # more agents than slots, enough timeouts starve the queue permanently:
        # every later request waits out OLLAMA_SEMAPHORE_TIMEOUT and is refused
        # as queue_saturation, while /health (which takes no slot) stays fast.
        # That is what wedged this server.
        #
        # Drain the slots the abandoned work was holding. release_slot() is
        # idempotent -- it catches the BoundedSemaphore over-release ValueError --
        # so the abandoned thread's own later release_slot() is a no-op and
        # nothing double-counts. Logged because a persistent drain rate means
        # threads are leaking and the real fix is cooperative cancellation.
        drained = _drain_slots_for_abandoned_request()
        log.warning(
            "provider_request_timeout_slots_drained",
            extra={
                "service": "free_harness_server",
                "event": "provider_request_timeout_slots_drained",
                "correlation_id": get_correlation_id() or get_request_id(),
                "timeout_s": REQUEST_TIMEOUT,
                "slots_drained": drained,
            },
        )
        raise HTTPException(
            status_code=504,
            detail=f"Provider timeout after {REQUEST_TIMEOUT:g}s",
        )'''

assert s.count(OLD) == 1, "timeout anchor=%d" % s.count(OLD)
s = s.replace(OLD, NEW, 1)

HELPER = '''
# Providers whose slots are acquired in FreeHarness._call_model. Kept in step
# with the set in that function's acquire/release guards; if one changes there it
# must change here, or a drained slot would be the wrong provider's.
_SLOT_PROVIDERS = ("nim", "ollama", "localai")


def _drain_slots_for_abandoned_request() -> int:
    """Release the semaphore slots held by a request that timed out.

    Best-effort by design. A failure here must not replace the 504 the caller is
    already owed, and the slots are only a throughput gate, so returning 0 on
    any error is correct: the worst case is the queue staying saturated, which
    is the state we are escaping, not a worse one.
    """
    released = 0
    try:
        for name in _SLOT_PROVIDERS:
            try:
                RATE_LIMITER.release_slot(name)
                released += 1
            except Exception:  # noqa: BLE001 - never mask the timeout
                continue
    except Exception:  # noqa: BLE001
        return released
    return released


'''
anchor = "async def chat_completions(request: Request):"
assert s.count(anchor) == 1, "handler anchor=%d" % s.count(anchor)
s = s.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

p.write_text(s, encoding="utf-8")
print("  timeout now drains abandoned slots instead of starving the queue")
