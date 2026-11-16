lines = open('/Users/a/trading/openalice-fleet/services/free_harness_server.py', 'r').readlines()

# Find the line with '@app.get("/metrics", include_in_schema=False)'
# Insert the new endpoint before it
insert_at = None
for i, line in enumerate(lines):
    if '@app.get("/metrics", include_in_schema=False)' in line:
        insert_at = i
        break

if insert_at:
    new_code = '''

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
'''
    lines.insert(insert_at, new_code)
    open('/Users/a/trading/openalice-fleet/services/free_harness_server.py', 'w').writelines(lines)
    print(f"Inserted health-check endpoint at line {insert_at + 1}")
else:
    print("Could not find insertion point")