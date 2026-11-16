# E2E Health Check Endpoint Design

## Route
GET /api/health-check

## Response Schema (200 OK)
{
  "ok": true,
  "service": "free_harness",
  "version": "1.0.0",
  "timestamp": "<ISO 8601>",
  "checks": {
    "nvidia_provider": "ok",
    "task_queue": "ok",
    "hive": "ok"
  }
}

## Error Handling
- 503 if any check fails, with "ok": false and details
- Content-Type: application/json

## Implementation Notes
- Read-only endpoint, no authentication required
- Backend Engineer to implement in free_harness_server.py
- QA Engineer to verify with curl and status code assertions