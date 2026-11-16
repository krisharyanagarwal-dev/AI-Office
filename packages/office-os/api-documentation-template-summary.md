# Documentation Template: Internal API Docs (Task ID: 3e63dec6)

## File Created/Modified
- **Path:** `/Users/aryanagarwal/office-os/api-documentation-template.md`
- **Task ID:** 3e63dec6
- **Priority:** normal

## Decisions Made

1. **Structure:** Kept the existing markdown template foundation (which already had all six required sections) and enhanced it rather than creating from scratch.
2. **Bilingual error codes:** Added `Message (ES)` column to the error codes table and `message_es` field in the example error response shape, so Spanish‑speaking users get human‑readable messages without machine translation.
3. **Register/dialect awareness:** Added explicit note in **Next Steps** that the Spanish translation should use a *neutral register* suitable for both Iberian and Latin‑American audiences, and that any terms without a safe equivalent must be flagged for human verification.
4. **Enhanced authentication section:** Added JWT token format details (`sub`, `aud`, `iat`, `exp`), scope cheat sheet, and rate‑limit context.
5. **Rate limits:** Detailed headers (`X-Rate-Limit-Limit`, `X-Rate-Limit-Remaining`, `X-Rate-Limit-Reset`, `Retry-After`), back‑off strategy, and linkage to 429/ERR_RATE_LIMIT.
6. **Versioning & deprecation:** Added sunset date, backward‑compatible changes note, and migration guide link placeholder.
7. **Decisions Made section:** Kept the existing bullet list documenting technical choices (HTTP/1.1, JSON, Bearer tokens, rate‑limit headers).
8. **Next Steps:** Re‑ordered and expanded to include concrete actions (populate endpoints, add real examples, define auth URLs, review error codes with security, publish, set quarterly review, translate with human flagging).

## Template Sections (All Present)

| Section | Status |
|---------|--------|
| 1. Overview | ✅ Purpose, audience, versioning, contact |
| 2. Authentication | ✅ Mechanism, headers, flows, scopes, JWT format, scope cheat sheet, rate‑limit context |
| 3. Endpoints | ✅ Method/path/description/auth table, example with query params and response schema |
| 4. Request/Response Examples | ✅ cURL, HTTP request line/headers, JSON payload/response snippets |
| 5. Error Codes | ✅ HTTP status, internal code, Message (EN), Message (ES), Guidance; consistent `{error, message, message_es, request_id}` shape |
| 6. Rate Limits | ✅ General/per‑endpoint limits, mandatory response headers, back‑off strategy, 429/ERR_RATE_LIMIT linkage |
| 7. Versioning & Deprecation | ✅ Current version, deprecation policy, migration guide, sunset date, backward‑compatible changes |
| 8. Additional Sections | ✅ Webhooks, OpenAPI/Swagger, change log, known issues |
| 📌 Decisions Made | ✅ Technical choices documented |
| 🛠️ Next Steps | ✅ Populate, review, publish, quarterly review, translate with human flagging |

## Flagged Untranslatable Terms (for Human Verification)

- **"Rate limits"** → Spanish: "límites de tasa" (confirmed equivalent, but must be verified per locale)
- Any locale‑specific technical terminology should be checked by a human reviewer before publishing the Spanish version.

## Next Steps

1. Populate the **Endpoints** table with actual routes from the codebase.
2. Add real **request/response** examples from the first two internal services.
3. Define the **auth service** URLs and JWT token format.
4. Review error‑code mappings with the security team and confirm bilingual messages.
5. Publish the markdown file to the internal docs site and link from the developer portal.
6. Schedule a **quarterly review** cadence to keep the docs in sync with code changes.
7. Translate this template into Spanish using a *neutral register* suitable for both Iberian and Latin‑American audiences; flag any terms that may not have a direct equivalent for a human to check.

---
*This template follows a neutral register suitable for both Iberian and Latin‑American Spanish audiences. All placeholders are marked with angle brackets (`<…>`) or double braces (`{{…}}`) for easy substitution.*