# Internal API Documentation Template

**Version:** 1.0
**Last Updated:** {{DATE}}
**Owner:** {{TEAM/OWNER}}
**Status:** 📝 Draft / 🟢 Approved / 🔴 Deprecated

---

## 1. Overview

- **Purpose:** Brief description of the API's role and what problem it solves.
- **Scope:** List of resources, supported operations, and any exclusions.
- **Target Audience:** Internal developers, partners, or integrators.
- **Dependencies:** Other APIs, services, or libraries required.

---

## 2. Authentication

| Method | Description | Headers / Parameters | Example |
|--------|-------------|----------------------|---------|
| **Bearer Token** | OAuth 2.0 / JWT | `Authorization: Bearer <token>` | `Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` |
| **API Key** | Simple key‑based auth | `X-API-Key: <key>` | `X-API-Key: abc123xyz` |
| **Mutual TLS** | Certificate‑based | TLS client certificate | *See mTLS setup guide* |

> **Note:** Replace placeholder values with actual credentials from the secrets manager.

---

## 3. Endpoints

### 3.1 Conventions

- **Base URL:** `https://api.internal.example.com/v1`
- **HTTP Methods:** GET, POST, PUT, PATCH, DELETE
- **Content-Type:** `application/json` (unless otherwise noted)
- **URL Parameters:** Use `{param}` style, described per endpoint.
- **Query Parameters:** Listed per endpoint, include default values if any.

### 3.2 Endpoint Catalog

| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| `GET` | `/health` | Return service health status. | None | 100/min |
| `GET` | `/users` | List all users (paginated). | Bearer | 60/min |
| `POST` | `/users` | Create a new user. | Bearer | 30/min |
| `GET` | `/users/{id}` | Retrieve a user by ID. | Bearer | 60/min |
| `PUT` | `/users/{id}` | Update a user. | Bearer | 30/min |
| `DELETE` | `/users/{id}` | Soft‑delete a user. | Bearer | 30/min |
| *…add more as needed* | | | | |

> **Tip:** Use the `{{BASE_URL}}` variable in your IDE or documentation generator to keep URLs environment‑agnostic.

---

## 4. Request / Response Examples

### 4.1 Successful Request

```http
GET /users HTTP/1.1
Host: api.internal.example.com
Authorization: Bearer <valid-token>
Accept: application/json
```

### 4.2 Successful Response (200 OK)

```json
{
  "data": [
    {
      "id": "12345",
      "name": "Alice",
      "email": "alice@example.com",
      "createdAt": "2025-03-15T08:22:11Z"
    }
  ],
  "meta": {
    "page": 1,
    "pageSize": 20,
    "total": 127
  }
}
```

### 4.3 Error Response

```json
{
  "error": {
    "code": "ERR_001",
    "message": "User not found",
    "details": null
  }
}
```

> **Pattern:** All error objects follow the shape `{ "error": { "code": "...", "message": "...", "details": null | {...} } }`.

---

## 5. Error Codes

| Code | HTTP Status | Meaning | Resolution |
|------|-------------|---------|------------|
| `ERR_000` | 400 | Bad Request – invalid payload | Check request format / required fields |
| `ERR_001` | 404 | Not Found – resource does not exist | Verify ID or filter parameters |
| `ERR_002` | 401 | Unauthorized – missing or invalid token | Provide a valid Bearer token or API key |
| `ERR_003` | 403 | Forbidden – insufficient scopes | Request the required scope / contact admin |
| `ERR_004` | 429 | Too Many Requests – rate limit exceeded | Back off and retry after `Retry-After` header |
| `ERR_500` | 500 | Internal Server Error – unexpected condition | Retry later; log ticket if persistent |
| *…add application‑specific codes* | | | |

---

## 6. Rate Limits

| Scope | Limit | Window | Headers |
|-------|-------|--------|---------|
| **General** | 100 requests/min | per IP / token | `X-RateLimit-Limit: 100`, `X-RateLimit-Remaining: 95`, `X-RateLimit-Reset: <epoch>` |
| **Authenticated Users** | 60 requests/min | per user ID | Same headers as General |
| **Write Operations** | 30 requests/min | per endpoint | `X-RateLimit-Reset` indicates when the counter resets |

- **Retry‑After:** Included in 429 responses, indicating seconds until the limit resets.
- **Back‑off Strategy:** Exponential jitter: wait `2^n + random(0,1)` seconds, up to a maximum of 30 s.

---

## 7. Versioning & Change Log

- **Major:** Breaking changes – bump `v1 → v2`, deprecate old endpoints after 90 days.
- **Minor:** Non‑breaking additions – incremental version `v1.1`, `v1.2`, etc.
- **Patch:** Documentation or schema fixes – no version bump required.

**Change Log:**

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| 1.0 | {{DATE}} | {{AUTHOR}} | Initial template |

---

## 8. Additional Sections (optional)

- **Webhooks:** URL registration, payload format, security (HMAC signature).
- **SDKs:** Links to client libraries (e.g., `npm i @internal/api`).
- **Testing:** Sandbox environment URL, test credentials.
- **Support:** Contact channel, response SLA.

---

### 📌 Quick Checklist Before Publishing

- [ ] All placeholders replaced (`{{DATE}}`, `{{TEAM/OWNER}}`, `{{BASE_URL}}`).
- [ ] Authentication section matches the actual mechanism used.
- [ ] Endpoint list reflects the current contract (no stale URLs).
- [ ] Error codes are exhaustive and mapped to HTTP statuses.
- [ ] Rate‑limit headers are documented and tested.
- [ ] Examples compile and return the expected schema (run a quick `curl` check).
- [ ] Document reviewed by at least one peer.

--- 

*End of Template*