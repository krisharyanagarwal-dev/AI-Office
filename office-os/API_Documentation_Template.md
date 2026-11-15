# Internal API Documentation Template

**API Name:** {{API_NAME}}
**Version:** {{VERSION}}
**Environment:** {{ENVIRONMENT}} (e.g., development, staging, production)
**Base URL:** {{BASE_URL}}

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication](#2-authentication)
3. [Endpoints](#3-endpoints)
4. [Request & Response Examples](#4-request--response-examples)
5. [Error Codes](#5-error-codes)
6. [Rate Limits](#6-rate-limits)
7. [Versioning](#7-versioning)
8. [SDKs](#8-sdks)

---

## 1. Overview

Provide a high-level description of the API's purpose, the problem it solves, and key concepts.

- **Purpose:** Brief description of what this API does.
- **Target Audience:** Who should use this API (internal teams, partners, etc.).
- **Dependencies:** Other APIs or services this depends on.
- **Changelog Link:** Link to the change log or release notes.

**Example:**

> This API provides programmatic access to manage user accounts and authentication for the internal platform. It handles user creation, password resets, and profile updates. Depends on the User Management Service for data persistence.

---

## 2. Authentication

Describe how clients authenticate with the API. Include all supported methods, token format, and header requirements.

> **Important:** Never expose secrets in client-facing documentation. Use placeholders like `<YOUR_API_KEY>` or `<TOKEN>`.

### 2.1 Supported Methods

| Method | Description | Required Scopes |
|--------|-------------|-----------------|
| API Key | Static key passed via header or query parameter. | `api_access` |
| OAuth 2.0 | Flow-dependent (Authorization Code, Client Credentials). | `openid`, `profile` |
| SSO | Single sign-on via identity provider. | `sso_access` |

### 2.2 API Key Authentication

> **Header:** `Authorization: Bearer <API_KEY>`
> **Query Parameter:** `api_key=<API_KEY>`

```bash
curl -H "Authorization: Bearer sk_live_abc123def456" \
  https://api.example.com/v1/users
```

### 2.3 OAuth 2.0

> **Token Endpoint:** `POST /oauth/token`
> **Grant Types:** Authorization Code, Client Credentials, Refresh Token.
> **Token Format:** JWT signed with RS256.

### 2.4 Revoking Tokens

> **Endpoint:** `POST /auth/revoke`
> **Description:** Invalidate a refresh token or API key.

---

## 3. Endpoints

List all available endpoints organized by resource or functionality. For each endpoint, include:

- **Method** (GET, POST, PUT, DELETE, PATCH)
- **Path** (relative to base URL)
- **Description**
- **Auth Required:** Yes/No and method
- **Rate Limit Tier:** If different from default

### 3.1 Example Endpoint Table

| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| `GET` | `/v1/users` | List all users | Required | Standard |
| `POST` | `/v1/users` | Create a new user | Required | Standard |
| `GET` | `/v1/users/{id}` | Get a user by ID | Required | Standard |
| `PUT` | `/v1/users/{id}` | Update a user | Required | Standard |
| `DELETE` | `/v1/users/{id}` | Delete a user | Required | Strict |

> **Tip:** Use a consistent URL pattern (plural nouns, version prefix `/v1/`, lowercase, hyphens for separation).

### 3.2 Filtering & Pagination

Document how pagination and filtering work across list endpoints.

- **Pagination:** Cursor-based or offset-based? Page size defaults?
- **Filtering:** Query parameter format (e.g., `?status=active&role=admin`).
- **Sorting:** Default sort field, available options.

---

## 4. Request & Response Examples

Provide concrete, runnable examples for common operations. Use `curl`, HTTPie, or language SDKs.

### 4.1 Create a User (POST /v1/users)

**Request:**

```bash
curl -X POST "https://api.example.com/v1/users" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jane Doe",
    "email": "jane.doe@example.com",
    "role": "member",
    "settings": {
      "notifications": true,
      "theme": "dark"
    }
  }'
```

**Response (201 Created):**

```json
{
  "id": "usr_01H8xYZABcDeFgHiJkLmNo",
  "name": "Jane Doe",
  "email": "jane.doe@example.com",
  "role": "member",
  "status": "active",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique user identifier |
| `name` | string | Full name |
| `email` | string | Validated email address |
| `role` | string | User role/permissions |
| `status` | string | Account status (`active`, `suspended`, `deleted`) |
| `created_at` | ISO 8601 timestamp | When the account was created |
| `updated_at` | ISO 8601 timestamp | Last modification time |

### 4.2 Error Response Format

All errors follow a consistent envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request was malformed.",
    "details": [
      {
        "field": "email",
        "issue": "Must be a valid email address."
      }
    ],
    "request_id": "req_12345abcde"
  }
}
```

---

## 5. Error Codes

Standard HTTP status codes apply, but the API also returns structured error objects. Document all custom/non-standard codes.

| Status Code | Code (Internal) | Meaning | Resolution |
|-------------|-----------------|---------|------------|
| `400` | `BAD_REQUEST` | Invalid request payload or parameters. | Check request format and required fields. |
| `401` | `UNAUTHORIZED` | Missing or invalid authentication. | Provide valid token/API key. |
| `403` | `FORBIDDEN` | Authenticated but not authorized for this resource. | Verify scopes/permissions. |
| `404` | `NOT_FOUND` | Requested resource does not exist. | Verify ID/path parameters. |
| `409` | `CONFLICT` | Resource conflict (e.g., duplicate email). | Resolve conflict and retry. |
| `422` | `VALIDATION_ERROR` | Request validation failed. | Review `details` array for field-level errors. |
| `429` | `TOO_MANY_REQUESTS` | Rate limit exceeded. | Back off and retry after `Retry-After` header. |
| `500` | `INTERNAL_ERROR` | Unexpected server error. | Contact engineering team; include `request_id`. |
| `503` | `SERVICE_UNAVAILABLE` | Dependent service is down. | Retry with exponential backoff. |

> **Note:** Always inspect the `error.code` field inside the response body for the most specific error information, regardless of HTTP status.

### 5.1 Validation Error Details

When `error.code` is `VALIDATION_ERROR`, the `details` array contains one object per invalid field:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
      {
        "field": "password",
        "issue": "Must be at least 8 characters and contain a number."
      },
      {
        "field": "terms",
        "issue": "Must be accepted to proceed."
      }
    ]
  }
}
```

---

## 6. Rate Limits

Describe the throttling policy to help clients avoid `429` responses.

| Tier | Requests/Window | Window | Burst Allowance | Headers |
|------|-----------------|--------|-----------------|---------|
| **Standard** | 100 | per minute | 20 requests burst | `X-RateLimit-Limit: 100`, `X-RateLimit-Remaining: 95`, `X-RateLimit-Reset: UNIX_timestamp` |
| **Strict** | 30 | per minute | 10 requests burst | Same headers |
| **Partner** | 1000 | per hour | 100 requests burst | Same headers |

### 6.1 Rate Limit Headers

All responses include the following headers (when applicable):

- `X-RateLimit-Limit`: Maximum requests allowed in the window.
- `X-RateLimit-Remaining`: Requests remaining in the current window.
- `X-RateLimit-Reset`: UTC timestamp (seconds) when the window resets.
- `Retry-After`: Seconds to wait before retrying (returned with `429`).

### 6.2 Backoff Strategy

- **Initial retry:** Wait `Retry-After` seconds.
- **Exponential backoff:** If multiple retries fail, double the wait time.
- **Maximum backoff:** Cap at 60 seconds.
- **Jitter:** Add randomness (±20%) to avoid thundering herd.

---

## 7. Versioning

- **Current Version:** `v1` (as shown in base URL).
- **Version Strategy:** URL-path versioning (`/v1/`, `/v2/`, etc.).
- **Deprecation Policy:** Minor versions deprecated after 6 months, retired after 12 months.
- **Migration Guide:** Link to guide for moving from `v1` to `v2`.

> **Never remove or rename fields in a patch release.** Add new fields alongside existing ones.

---

## 8. SDKs

| Language | Package | Link |
|----------|---------|------|
| JavaScript/Node | `npm i @company/api-client` | [npm](https://www.npmjs.com/package/@company/api-client) |
| Python | `pip install company-api-client` | [PyPI](https://pypi.org/project/company-api-client/) |
| Go | `go get github.com/company/api-client-go` | [GitHub](https://github.com/company/api-client-go) |
| Java | `maven { groupId 'com.company', artifactId 'api-client' }` | [Maven Central](https://search.maven.org/artifact/com.company/api-client) |

> **Keep SDKs in sync with the API.** Mark deprecated endpoints in the docs and remove in the next major SDK version.

---

## Maintenance Checklist

- [ ] Review and update endpoint list quarterly.
- [ ] Verify all examples still run (CI check).
- [ ] Confirm error code mapping with QA.
- [ ] Update rate limit values if throttling policy changes.
- [ ] Check SDK compatibility on each release.
- [ ] Link to changelog for each version bump.

---

*Generated on {{DATE}} | Documentation for internal use only. Contact docs@company.com for updates.*