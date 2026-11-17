# THE CLAUDE COMPANY — Dost API Documentation

**Base URL:** `http://127.0.0.1:8083/api/v1`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Base URL](#base-url)
3. [Rate Limiting](#rate-limiting)
4. [Error Codes](#error-codes)
5. [Webhook Events](#webhook-events)
6. [Endpoints](#endpoints)
   - [POST /api/dispatch](#post-apidispatch)
   - [POST /api/debate](#post-apidebate)
   - [GET /api/tasks](#get-apitasks)
   - [GET /api/tasks/{task_id}](#get-apitasksid)
   - [GET /api/findings](#get-apifindings)
   - [GET /api/synthesis](#get-apisynthesis)
   - [GET /api/workspaces](#get-apiworkspaces)
   - [POST /api/workspaces](#post-apiworkspaces)
   - [GET /api/workspaces/{id}/tasks](#get-apiworkspacesidtasks)
   - [GET /api/workspaces/{id}/findings](#get-apiworkspacesidfindings)
   - [GET /api/workspaces/{id}/metrics](#get-apiworkspacesidmetrics)
   - [GET /api/workspaces/{id}/usage](#get-apiworkspacesidusage)
   - [GET /api/workspaces/{id}/cost](#get-apiworkspacesidcost)
   - [POST /api/task](#post-apitask)

---

## Authentication

Dost API uses **API key authentication**. Include your API key in the `Authorization` header of every request using the `Bearer` scheme.

### Header format

```
Authorization: Bearer <YOUR_API_KEY>
Content-Type: application/json
```

### Example (cURL)

```bash
curl -X POST http://127.0.0.1:8083/api/v1/api/dispatch \
  -H "Authorization: Bearer dost_live_abc123def456" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What is the capital of France?"}'
```

### Getting an API key

API keys are issued per workspace. Create a workspace via `POST /api/workspaces` to receive an API key, or retrieve it from the workspace settings in the Dost dashboard. Treat API keys as secrets — do not commit them to version control.

---

## Base URL

All endpoints are relative to:

```
http://127.0.0.1:8083/api/v1
```

Example full endpoint URL:

```
POST http://127.0.0.1:8083/api/v1/api/dispatch
```

---

## Rate Limiting

The Dost API enforces rate limits per API key to protect the service and ensure fair usage.

| Tier | Requests per minute | Requests per hour |
|------|---------------------|-------------------|
| Free | 60 | 1,000 |
| Pro | 300 | 50,000 |
| Enterprise | Custom | Custom |

### Rate limit headers

Every response includes the following headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests allowed in the current window |
| `X-RateLimit-Remaining` | Requests remaining in the current window |
| `X-RateLimit-Reset` | Unix timestamp when the rate limit window resets |

### Rate limit exceeded response

When you exceed your rate limit, the API returns HTTP `429 Too Many Requests`:

```json
{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again later.",
  "retry_after": 36
}
```

Retry after the number of seconds specified in the `retry_after` field (or the `Retry-After` response header).

---

## Error Codes

Dost uses standard HTTP status codes and returns a JSON error body.

| Status Code | Meaning |
|-------------|---------|
| 200 | OK — request succeeded |
| 201 | Created — resource created successfully |
| 400 | Bad Request — invalid request body or parameters |
| 401 | Unauthorized — missing or invalid API key |
| 403 | Forbidden — API key lacks permission for this resource |
| 404 | Not Found — resource does not exist |
| 409 | Conflict — resource already exists or state conflict |
| 422 | Unprocessable Entity — validation error |
| 429 | Too Many Requests — rate limit exceeded |
| 500 | Internal Server Error — unexpected server error |
| 503 | Service Unavailable — service temporarily down |

### Error response format

```json
{
  "error": "invalid_request",
  "message": "The 'prompt' field is required.",
  "request_id": "req_abc123def456"
}
```

| Field | Description |
|-------|-------------|
| `error` | Machine-readable error code |
| `message` | Human-readable description |
| `request_id` | Unique ID for debugging/support |

---

## Webhook Events

Dost can send webhook notifications when tasks complete, findings are created, or usage thresholds are reached. Configure webhook endpoints in your workspace settings.

### Webhook payload format

```json
{
  "event": "task.completed",
  "workspace_id": "ws_abc123",
  "timestamp": "2026-11-18T10:30:00Z",
  "data": {
    "task_id": "task_xyz789",
    "status": "completed",
    "result": "..."
  }
}
```

| Field | Description |
|-------|-------------|
| `event` | Webhook event type |
| `workspace_id` | ID of the workspace that triggered the event |
| `timestamp` | ISO 8601 UTC timestamp |
| `data` | Event-specific payload |

### Supported webhook events

| Event | Description |
|-------|-------------|
| `task.created` | A new task was created |
| `task.running` | A task started execution |
| `task.completed` | A task completed successfully |
| `task.failed` | A task failed |
| `finding.created` | A research finding was created |
| `synthesis.ready` | A synthesis report is ready |
| `usage.threshold` | Workspace usage reached a configured threshold |
| `cost.alert` | Workspace cost exceeded a configured alert |

### Webhook signature verification

Each webhook request includes a `Dost-Signature` header. Verify it using your workspace webhook secret to confirm the payload originated from Dost.

---

## Endpoints

### POST /api/dispatch

Submit a prompt to the fleet for processing.

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | The prompt to dispatch to the fleet |
| `workspace_id` | string | No | Target workspace ID |
| `model` | string | No | Preferred model (default: fleet default) |
| `temperature` | number | No | Sampling temperature 0–2 (default: 0.7) |
| `max_tokens` | integer | No | Maximum tokens in response |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | ID of the created task |
| `status` | string | Initial task status (`queued`) |
| `created_at` | string | ISO 8601 timestamp |

**Example request**

```bash
curl -X POST http://127.0.0.1:8083/api/v1/api/dispatch \
  -H "Authorization: Bearer dost_live_abc123def456" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Summarize the key trends in renewable energy for 2026.",
    "temperature": 0.5,
    "max_tokens": 500
  }'
```

**Example response**

```json
{
  "task_id": "task_xyz789",
  "status": "queued",
  "created_at": "2026-11-18T10:30:00Z"
}
```

---

### POST /api/debate

Start a multi-agent debate on a given topic.

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | Yes | The debate topic or question |
| `workspace_id` | string | No | Target workspace ID |
| `rounds` | integer | No | Number of debate rounds (default: 3) |
| `agents` | array | No | List of agent roles/perspectives |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `debate_id` | string | ID of the debate session |
| `status` | string | Initial status (`queued`) |
| `created_at` | string | ISO 8601 timestamp |

**Example request**

```bash
curl -X POST http://127.0.0.1:8083/api/v1/api/debate \
  -H "Authorization: Bearer dost_live_abc123def456" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Should remote work be the default for tech companies?",
    "rounds": 3,
    "agents": ["pro", "con", "moderator"]
  }'
```

**Example response**

```json
{
  "debate_id": "debate_abc123",
  "status": "queued",
  "created_at": "2026-11-18T10:30:00Z"
}
```

---

### GET /api/tasks

List dost tasks. Supports optional filtering by workspace and status.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workspace_id` | string | Filter tasks by workspace |
| `status` | string | Filter by status (`queued`, `running`, `completed`, `failed`) |
| `limit` | integer | Max results (default: 20, max: 100) |
| `offset` | integer | Pagination offset (default: 0) |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `tasks` | array | List of task objects |
| `total` | integer | Total count matching filters |
| `limit` | integer | Limit applied |
| `offset` | integer | Offset applied |

**Example request**

```bash
curl "http://127.0.0.1:8083/api/v1/api/tasks?workspace_id=ws_abc123&status=completed&limit=10" \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "tasks": [
    {
      "task_id": "task_xyz789",
      "workspace_id": "ws_abc123",
      "status": "completed",
      "prompt": "Summarize renewable energy trends",
      "created_at": "2026-11-18T10:30:00Z",
      "completed_at": "2026-11-18T10:32:15Z"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

---

### GET /api/tasks/{task_id}

Get details for a specific task.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `task_id` | string | The task ID |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Task ID |
| `workspace_id` | string | Workspace ID |
| `status` | string | Task status |
| `prompt` | string | Original prompt |
| `result` | string | Task result (if completed) |
| `created_at` | string | Creation timestamp |
| `completed_at` | string | Completion timestamp (if completed) |

**Example request**

```bash
curl http://127.0.0.1:8083/api/v1/api/tasks/task_xyz789 \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "task_id": "task_xyz789",
  "workspace_id": "ws_abc123",
  "status": "completed",
  "prompt": "Summarize renewable energy trends",
  "result": "Renewable energy adoption accelerated in 2026...",
  "created_at": "2026-11-18T10:30:00Z",
  "completed_at": "2026-11-18T10:32:15Z"
}
```

---

### GET /api/findings

List research findings across workspaces.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workspace_id` | string | Filter by workspace |
| `limit` | integer | Max results (default: 20, max: 100) |
| `offset` | integer | Pagination offset (default: 0) |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `findings` | array | List of finding objects |
| `total` | integer | Total count |
| `limit` | integer | Limit applied |
| `offset` | integer | Offset applied |

**Example request**

```bash
curl "http://127.0.0.1:8083/api/v1/api/findings?workspace_id=ws_abc123&limit=5" \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "findings": [
    {
      "finding_id": "finding_def456",
      "workspace_id": "ws_abc123",
      "title": "Solar cost decline trend",
      "content": "Solar PV costs have declined 85% over the last decade.",
      "source": "task_xyz789",
      "created_at": "2026-11-18T10:32:15Z"
    }
  ],
  "total": 1,
  "limit": 5,
  "offset": 0
}
```

---

### GET /api/synthesis

Get a synthesis report aggregating findings and task results.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workspace_id` | string | Workspace to synthesize |
| `format` | string | Output format (`json`, `markdown`, `pdf`) |

**Response** (JSON format)

| Field | Type | Description |
|-------|------|-------------|
| `report_id` | string | Synthesis report ID |
| `workspace_id` | string | Workspace ID |
| `summary` | string | Executive summary |
| `findings_summary` | array | Summarized findings |
| `generated_at` | string | Generation timestamp |

**Example request**

```bash
curl "http://127.0.0.1:8083/api/v1/api/synthesis?workspace_id=ws_abc123&format=json" \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "report_id": "report_ghi789",
  "workspace_id": "ws_abc123",
  "summary": "Key insights across 12 completed tasks...",
  "findings_summary": [
    "Solar costs down 85%",
    "Wind adoption rising in Europe"
  ],
  "generated_at": "2026-11-18T10:45:00Z"
}
```

---

### GET /api/workspaces

List all workspaces accessible to the API key.

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `workspaces` | array | List of workspace objects |
| `total` | integer | Total count |

**Example request**

```bash
curl http://127.0.0.1:8083/api/v1/api/workspaces \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "workspaces": [
    {
      "workspace_id": "ws_abc123",
      "name": "Research Team",
      "plan": "pro",
      "api_key": "dost_live_abc123def456",
      "created_at": "2026-10-01T00:00:00Z"
    }
  ],
  "total": 1
}
```

---

### POST /api/workspaces

Create a new workspace.

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Workspace name |
| `plan` | string | No | Plan tier (`free`, `pro`, `enterprise`) |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | string | New workspace ID |
| `name` | string | Workspace name |
| `api_key` | string | Workspace API key |
| `plan` | string | Plan tier |
| `created_at` | string | Creation timestamp |

**Example request**

```bash
curl -X POST http://127.0.0.1:8083/api/v1/api/workspaces \
  -H "Authorization: Bearer dost_live_abc123def456" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Research Team",
    "plan": "pro"
  }'
```

**Example response**

```json
{
  "workspace_id": "ws_abc123",
  "name": "Research Team",
  "api_key": "dost_live_abc123def456",
  "plan": "pro",
  "created_at": "2026-11-18T10:30:00Z"
}
```

---

### GET /api/workspaces/{id}/tasks

List tasks belonging to a specific workspace.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | Workspace ID |

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by task status |
| `limit` | integer | Max results |
| `offset` | integer | Pagination offset |

**Example request**

```bash
curl "http://127.0.0.1:8083/api/v1/api/workspaces/ws_abc123/tasks?status=completed" \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "workspace_id": "ws_abc123",
  "tasks": [
    {
      "task_id": "task_xyz789",
      "status": "completed",
      "prompt": "Summarize renewable energy trends",
      "created_at": "2026-11-18T10:30:00Z"
    }
  ],
  "total": 1
}
```

---

### GET /api/workspaces/{id}/findings

List findings belonging to a specific workspace.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | Workspace ID |

**Example request**

```bash
curl http://127.0.0.1:8083/api/v1/api/workspaces/ws_abc123/findings \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "workspace_id": "ws_abc123",
  "findings": [
    {
      "finding_id": "finding_def456",
      "title": "Solar cost decline trend",
      "content": "Solar PV costs have declined 85% over the last decade.",
      "created_at": "2026-11-18T10:32:15Z"
    }
  ],
  "total": 1
}
```

---

### GET /api/workspaces/{id}/metrics

Get aggregate metrics for a workspace.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | Workspace ID |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | string | Workspace ID |
| `total_tasks` | integer | Total tasks created |
| `completed_tasks` | integer | Tasks completed |
| `failed_tasks` | integer | Tasks failed |
| `avg_completion_time_seconds` | number | Average task completion time |
| `period_start` | string | Metrics period start |
| `period_end` | string | Metrics period end |

**Example request**

```bash
curl http://127.0.0.1:8083/api/v1/api/workspaces/ws_abc123/metrics \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "workspace_id": "ws_abc123",
  "total_tasks": 120,
  "completed_tasks": 110,
  "failed_tasks": 5,
  "avg_completion_time_seconds": 45.2,
  "period_start": "2026-11-01T00:00:00Z",
  "period_end": "2026-11-18T00:00:00Z"
}
```

---

### GET /api/workspaces/{id}/usage

Get usage statistics for a workspace.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | Workspace ID |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | string | Workspace ID |
| `requests_this_month` | integer | API requests this month |
| `tokens_used` | integer | Total tokens consumed |
| `tasks_run` | integer | Tasks executed |
| `plan_limit` | object | Plan limits |
| `reset_date` | string | Usage reset date |

**Example request**

```bash
curl http://127.0.0.1:8083/api/v1/api/workspaces/ws_abc123/usage \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "workspace_id": "ws_abc123",
  "requests_this_month": 850,
  "tokens_used": 450000,
  "tasks_run": 120,
  "plan_limit": {
    "requests_per_month": 50000,
    "tokens_per_month": 5000000
  },
  "reset_date": "2026-12-01T00:00:00Z"
}
```

---

### GET /api/workspaces/{id}/cost

Get cost breakdown for a workspace.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | Workspace ID |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | string | Workspace ID |
| `total_cost_usd` | number | Total cost in USD |
| `cost_by_model` | object | Cost broken down by model |
| `cost_by_task_type` | object | Cost broken down by task type |
| `period_start` | string | Period start |
| `period_end` | string | Period end |

**Example request**

```bash
curl http://127.0.0.1:8083/api/v1/api/workspaces/ws_abc123/cost \
  -H "Authorization: Bearer dost_live_abc123def456"
```

**Example response**

```json
{
  "workspace_id": "ws_abc123",
  "total_cost_usd": 42.50,
  "cost_by_model": {
    "dost-fleet-v1": 30.00,
    "dost-debate-v1": 12.50
  },
  "cost_by_task_type": {
    "dispatch": 30.00,
    "debate": 12.50
  },
  "period_start": "2026-11-01T00:00:00Z",
  "period_end": "2026-11-18T00:00:00Z"
}
```

---

### POST /api/task

Dashboard task trigger — creates and dispatches a task from the dashboard interface.

**Request body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | The task prompt |
| `workspace_id` | string | Yes | Target workspace ID |
| `priority` | string | No | Priority level (`low`, `normal`, `high`) |
| `callback_url` | string | No | Webhook URL for completion notification |

**Response**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Created task ID |
| `status` | string | Task status |
| `dashboard_url` | string | Link to view task in dashboard |

**Example request**

```bash
curl -X POST http://127.0.0.1:8083/api/v1/api/task \
  -H "Authorization: Bearer dost_live_abc123def456" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze Q3 sales data",
    "workspace_id": "ws_abc123",
    "priority": "high",
    "callback_url": "https://example.com/webhook"
  }'
```

**Example response**

```json
{
  "task_id": "task_dashboard_123",
  "status": "queued",
  "dashboard_url": "http://127.0.0.1:8083/dashboard/tasks/task_dashboard_123"
}
```

---

## SDK Examples

### JavaScript (fetch)

```javascript
const response = await fetch('http://127.0.0.1:8083/api/v1/api/dispatch', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer dost_live_abc123def456',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    prompt: 'What is the capital of France?',
    temperature: 0.7
  })
});
const data = await response.json();
console.log(data.task_id);
```

### Python (requests)

```python
import requests

headers = {
    'Authorization': 'Bearer dost_live_abc123def456',
    'Content-Type': 'application/json'
}

response = requests.post(
    'http://127.0.0.1:8083/api/v1/api/dispatch',
    headers=headers,
    json={'prompt': 'What is the capital of France?', 'temperature': 0.7}
)

data = response.json()
print(data['task_id'])
```

---

*Documentation generated for THE CLAUDE COMPANY — Dost API v1*
