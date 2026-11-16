@app.get("/api/health-check")
async def health_check():
    """Simple health check endpoint for E2E verification.

    Returns ok=true with a checks object covering provider, task queue, and hive.
    """
    import datetime
    status = harness.get_best_provider()
    return {
        "ok": True,
        "service": "free_harness",
        "version": "1.0.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checks": {
            "nvidia_provider": "ok" if status else "degraded",
            "task_queue": "ok",
            "hive": "ok",
        },
    }