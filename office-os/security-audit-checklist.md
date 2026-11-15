# Web Application Security Audit Checklist

**Version:** 1.0  
**Date:** 2026-11-05  
**Classification:** Internal - Security  
**Owner:** Security Architecture Team

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Authorization](#2-authorization)
3. [Input Validation](#3-input-validation)
4. [Output Encoding](#4-output-encoding)
5. [Session Management](#5-session-management)
6. [OWASP Top 10 (2021) Coverage](#6-owasp-top-10-2021-coverage)
7. [Cryptography & Key Management](#7-cryptography--key-management)
8. [API Security](#8-api-security)
9. [Infrastructure & Deployment](#9-infrastructure--deployment)
10. [Logging, Monitoring & Incident Response](#10-logging-monitoring--incident-response)
11. [Supply Chain & Dependencies](#11-supply-chain--dependencies)
12. [Compliance & Privacy](#12-compliance--privacy)
13. [Audit Execution Guide](#13-audit-execution-guide)

---

## 1. Authentication

### 1.1 Credential Handling
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| AUTH-01 | Passwords hashed with Argon2id (preferred), bcrypt, or PBKDF2 with ≥100k iterations | Critical | ☐ | |
| AUTH-02 | No plaintext or reversible encryption of passwords anywhere (logs, DB, memory dumps) | Critical | ☐ | |
| AUTH-03 | Password policy: min 12 chars, no max length limit, allow all Unicode, block breached passwords (HIBP) | High | ☐ | |
| AUTH-04 | Rate limiting on login: ≤5 attempts/min/IP, ≤20 attempts/hour/user, exponential backoff | Critical | ☐ | |
| AUTH-05 | Account lockout after failed attempts with secure unlock (email link, not auto-unlock) | High | ☐ | |
| AUTH-06 | Multi-factor authentication (TOTP, WebAuthn/FIDO2) enforced for all admin/high-privilege accounts | Critical | ☐ | |
| AUTH-07 | MFA optional but encouraged for all users; recovery codes generated and stored securely | High | ☐ | |
| AUTH-08 | Password reset: single-use, time-limited (≤15 min), high-entropy tokens, invalidated on use | Critical | ☐ | |
| AUTH-09 | No username enumeration in login, reset, or registration flows (consistent responses) | High | ☐ | |
| AUTH-10 | Authentication via OAuth2/OIDC with PKCE for public clients; validate `state` and `nonce` | High | ☐ | |

### 1.2 Session & Token Security
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| AUTH-11 | JWT: RS256/ES256 (asymmetric), short expiry (≤15 min access, ≤7 days refresh), `aud`/`iss` validated | Critical | ☐ | |
| AUTH-12 | Refresh tokens: rotating, single-use, bound to device/client, revoked on logout/password change | Critical | ☐ | |
| AUTH-13 | Tokens never in URLs; stored in Secure, HttpOnly, SameSite=Strict/Lax cookies or secure storage | Critical | ☐ | |
| AUTH-14 | Session invalidation on password change, MFA enable/disable, privilege change, suspicious activity | High | ☐ | |
| AUTH-15 | Concurrent session limits enforced; user can view/revoke active sessions | Medium | ☐ | |

### 1.3 Federation & SSO
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| AUTH-16 | SAML/OIDC: validate signatures, check assertions not replayed, enforce audience restriction | High | ☐ | |
| AUTH-17 | Just-in-time provisioning with attribute mapping reviewed; no auto-admin assignment | Medium | ☐ | |

---

## 2. Authorization

### 2.1 Access Control Model
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| AUTHZ-01 | Role-Based Access Control (RBAC) or Attribute-Based (ABAC) implemented centrally, not scattered | Critical | ☐ | |
| AUTHZ-02 | Default-deny: all endpoints require explicit authorization check | Critical | ☐ | |
| AUTHZ-03 | Authorization enforced at API/gateway layer, not just UI | Critical | ☐ | |
| AUTHZ-04 | Object-level authorization: users can only access objects they own/have permission for (no IDOR) | Critical | ☐ | |
| AUTHZ-05 | Horizontal privilege escalation tested: user A cannot access user B's resources | Critical | ☐ | |
| AUTHZ-06 | Vertical privilege escalation tested: standard user cannot access admin endpoints | Critical | ☐ | |

### 2.2 Implementation
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| AUTHZ-07 | Centralized policy decision point (PDP) or middleware; no inline `if (user.role === 'admin')` | High | ☐ | |
| AUTHZ-08 | Permissions as fine-grained scopes/claims, not coarse roles only | Medium | ☐ | |
| AUTHZ-09 | Admin actions require re-authentication (step-up auth) or MFA challenge | High | ☐ | |
| AUTHZ-10 | API keys/scoped tokens for service-to-service; rotated, auditable, least privilege | High | ☐ | |

---

## 3. Input Validation

### 3.1 Validation Strategy
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| INP-01 | Allow-list validation on all inputs (type, length, format, range); reject-list only as defense-in-depth | Critical | ☐ | |
| INP-02 | Validation at trust boundaries: API gateway, controllers, service layer, database | High | ☐ | |
| INP-03 | Structured validation libraries used (Zod, Joi, Pydantic, class-validator); no hand-rolled regex for complex types | High | ☐ | |
| INP-04 | File uploads: MIME type verified via magic bytes, extension allow-listed, size limited, scanned for malware | Critical | ☐ | |
| INP-05 | File uploads stored outside webroot, served via signed URLs or authenticated proxy, no direct execution | Critical | ☐ | |

### 3.2 Specific Vectors
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| INP-06 | SQL/NoSQL: parameterized queries / prepared statements everywhere; no string concatenation | Critical | ☐ | |
| INP-07 | ORM/ODM used correctly; raw queries audited | High | ☐ | |
| INP-08 | LDAP injection: input sanitized for DN/filter construction | Medium | ☐ | |
| INP-09 | Command injection: no `exec`/`system`/shell with user input; allow-listed commands only | Critical | ☐ | |
| INP-10 | Path traversal: canonicalize paths, restrict to allow-listed directories | Critical | ☐ | |
| INP-11 | XXE: XML parsers configured with `DISALLOW_DOCTYPE`, external entity resolution disabled | High | ☐ | |
| INP-12 | Deserialization: no untrusted data deserialized (Java, .NET, Python pickle, PHP, Node `eval`) | Critical | ☐ | |
| INP-13 | SSRF: outbound requests to allow-listed hosts only; deny RFC1918, localhost, metadata endpoints | Critical | ☐ | |
| INP-14 | Template injection: user input never in template strings; sandboxed template engines | High | ☐ | |
| INP-15 | Prototype pollution (JS): `Object.freeze(Object.prototype)`, schema validation before merge | Medium | ☐ | |

---

## 4. Output Encoding

### 4.1 Context-Aware Encoding
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| OUT-01 | HTML context: HTML-encode (`&`, `<`, `>`, `"`, `'`) via template engine auto-escaping | Critical | ☐ | |
| OUT-02 | HTML attribute context: attribute-encode (quotes, spaces, `>`); never unquoted attributes | Critical | ☐ | |
| OUT-03 | JavaScript context: JS-encode for data in `<script>` or event handlers; prefer `data-` attributes + `JSON.parse` | Critical | ☐ | |
| OUT-04 | CSS context: CSS-encode; avoid user input in `<style>` or `style=` | Medium | ☐ | |
| OUT-05 | URL context: URL-encode query params; validate full URLs for navigation | High | ☐ | |
| OUT-06 | SQL context: not needed if parameterized queries used (see INP-06) | N/A | ☐ | |

### 4.2 Response Headers
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| OUT-07 | `Content-Type` with charset on all responses; no sniffing | High | ☐ | |
| OUT-08 | `X-Content-Type-Options: nosniff` | High | ☐ | |
| OUT-09 | `Content-Security-Policy` restrictive: `default-src 'self'`, no `unsafe-inline`, no `unsafe-eval`, `frame-ancestors 'none'` | Critical | ☐ | |
| OUT-10 | CSP: `report-uri`/`report-to` configured; violations monitored | Medium | ☐ | |
| OUT-11 | `X-Frame-Options: DENY` or `frame-ancestors` in CSP | High | ☐ | |
| OUT-12 | `Referrer-Policy: strict-origin-when-cross-origin` or stricter | Medium | ☐ | |
| OUT-13 | `Permissions-Policy` (Feature-Policy) restricting geolocation, camera, microphone, payment, etc. | Medium | ☐ | |
| OUT-14 | `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` | Medium | ☐ | |

---

## 5. Session Management

| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| SESS-01 | Session IDs: cryptographically random, ≥128 bits entropy, generated by CSPRNG | Critical | ☐ | |
| SESS-02 | Cookies: `Secure`, `HttpOnly`, `SameSite=Strict` (or `Lax` with CSRF token), `__Host-` prefix | Critical | ☐ | |
| SESS-03 | Session timeout: ≤15 min idle, ≤12 hours absolute; configurable per sensitivity | High | ☐ | |
| SESS-04 | Session rotation on privilege change (login, MFA, role change) | High | ☐ | |
| SESS-05 | Secure logout: server-side session destruction, client-side cookie clearing, token revocation | Critical | ☐ | |
| SESS-06 | No session fixation: new session ID on login, old invalidated | Critical | ☐ | |
| SESS-07 | Session data: minimal PII, encrypted at rest if sensitive | Medium | ☐ | |
| SESS-08 | Distributed sessions: shared store (Redis) with TLS, proper key expiration, no local file storage | High | ☐ | |

---

## 6. OWASP Top 10 (2021) Coverage

| OWASP Category | ID | Specific Checks | Priority | Status |
|----------------|-----|-----------------|----------|--------|
| **A01: Broken Access Control** | OWASP-01 | AUTHZ-01 through AUTHZ-10 | Critical | ☐ |
| **A02: Cryptographic Failures** | OWASP-02 | CRYPTO-01 through CRYPTO-12 (see Section 7) | Critical | ☐ |
| **A03: Injection** | OWASP-03 | INP-06, INP-07, INP-08, INP-09, INP-11, INP-12 | Critical | ☐ |
| **A04: Insecure Design** | OWASP-04 | Threat modeling done; secure design patterns; no business logic flaws (e.g., coupon reuse, race conditions) | High | ☐ |
| **A05: Security Misconfiguration** | OWASP-05 | INFRA-01 through INFRA-12 (see Section 9); default creds removed; debug disabled | Critical | ☐ |
| **A06: Vulnerable Components** | OWASP-06 | DEP-01 through DEP-08 (see Section 11); SBOM; automated scanning | Critical | ☐ |
| **A07: Identification & Authentication Failures** | OWASP-07 | AUTH-01 through AUTH-17 | Critical | ☐ |
| **A08: Software & Data Integrity Failures** | OWASP-08 | CI/CD integrity (INFRA-09), signed artifacts, dependency verification, no unsigned scripts | High | ☐ |
| **A09: Security Logging & Monitoring Failures** | OWASP-09 | LOG-01 through LOG-10 (see Section 10) | Critical | ☐ |
| **A10: Server-Side Request Forgery (SSRF)** | OWASP-10 | INP-13; egress filtering; metadata service blocking | Critical | ☐ |

---

## 7. Cryptography & Key Management

| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| CRYPTO-01 | TLS 1.2+ everywhere; TLS 1.3 preferred; certs from trusted CA; HSTS with preload | Critical | ☐ | |
| CRYPTO-02 | Certificates: 2048-bit RSA or ECDSA P-256; no SHA-1; rotated before expiry; CT monitoring | High | ☐ | |
| CRYPTO-03 | Data at rest: AES-256-GCM or ChaCha20-Poly1305; keys managed by KMS/HSM, not in code/config | Critical | ☐ | |
| CRYPTO-04 | Data in transit: TLS for all internal service communication (mTLS preferred) | High | ☐ | |
| CRYPTO-05 | Key rotation: automated, ≤90 days for data keys, ≤1 year for root/KEK; old keys retained for decrypt | High | ☐ | |
| CRYPTO-06 | No hardcoded secrets, API keys, or crypto keys in source, Docker images, CI/CD vars | Critical | ☐ | |
| CRYPTO-07 | Secrets management: Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret Manager; audit access | Critical | ☐ | |
| CRYPTO-08 | Password hashing: Argon2id (memory-hard), bcrypt, or PBKDF2; cost factors current (see AUTH-01) | Critical | ☐ | |
| CRYPTO-09 | Random numbers: CSPRNG only (`crypto.randomBytes`, `secrets`, `getrandom`); no `Math.random` | High | ☐ | |
| CRYPTO-10 | Digital signatures: Ed25519 or RSA-PSS; verify before trust; timestamping for non-repudiation | Medium | ☐ | |
| CRYPTO-11 | Certificate pinning for mobile/API clients; fallback strategy for rotation | Medium | ☐ | |
| CRYPTO-12 | Post-quantum readiness: inventory crypto; plan for hybrid KEM (ML-KEM + ECDH) | Low | ☐ | |

---

## 8. API Security

| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| API-01 | OpenAPI/Swagger spec exists, versioned, validated in CI; no undocumented endpoints | High | ☐ | |
| API-02 | Rate limiting: per-client (API key/user), tiered quotas, burst protection, 429 with `Retry-After` | Critical | ☐ | |
| API-03 | Input validation on all parameters (path, query, header, body); schema enforcement | Critical | ☐ | |
| API-04 | Output encoding / safe serialization; no mass assignment (allow-list fields) | High | ☐ | |
| API-05 | Authentication required by default; public endpoints explicitly marked | Critical | ☐ | |
| API-06 | Authorization at resource level (see AUTHZ-04); no IDOR via predictable IDs (use UUIDs/ULIDs) | Critical | ☐ | |
| API-07 | CORS: restrictive `Access-Control-Allow-Origin` (no `*` with credentials), no `null` origin | High | ☐ | |
| API-08 | GraphQL: depth limiting, cost analysis, query allow-listing, introspection disabled in prod | High | ☐ | |
| API-09 | Webhooks: signature verification (HMAC), replay protection (timestamp + nonce), idempotency keys | Critical | ☐ | |
| API-10 | Error responses: no stack traces, no PII, consistent format, generic messages | Medium | ☐ | |
| API-11 | API versioning in URL or header; deprecation policy; sunset headers | Medium | ☐ | |

---

## 9. Infrastructure & Deployment

### 9.1 Network & Host Hardening
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| INFRA-01 | Network segmentation: public, private, data tiers; no direct DB access from internet | Critical | ☐ | |
| INFRA-02 | WAF/Shield: managed rules (OWASP CRS), custom rules for app-specific attacks, block mode in prod | High | ☐ | |
| INFRA-03 | DDoS protection: L3/L4 (cloud provider) + L7 (WAF/rate limiting) | High | ☐ | |
| INFRA-04 | Host hardening: minimal packages, no SSH password auth, automated patching, CIS benchmarks | High | ☐ | |
| INFRA-05 | Container security: distroless/minimal base images, non-root user, read-only rootfs, no secrets in layers | High | ☐ | |

### 9.2 CI/CD & Supply Chain
| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| INFRA-06 | Pipeline: signed commits, required reviews, status checks, no direct pushes to main | High | ☐ | |
| INFRA-07 | Build: reproducible, hermetic, SBOM generated (CycloneDX/SPDX), SLSA Level 2+ target | Medium | ☐ | |
| INFRA-08 | Artifacts: signed (cosign/sigstore), verified on deploy; provenance attestation | High | ☐ | |
| INFRA-09 | Deployment: blue/green or canary; automated rollback on health check failure; zero-downtime | Medium | ☐ | |
| INFRA-10 | Infrastructure as Code: Terraform/Pulumi; policy-as-code (OPA/Rego); drift detection | Medium | ☐ | |
| INFRA-11 | Secrets in CI: only via secret manager; no plaintext in logs; masked in output | Critical | ☐ | |
| INFRA-12 | Immutable infrastructure: no SSH to prod; changes via pipeline only | High | ☐ | |

---

## 10. Logging, Monitoring & Incident Response

| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| LOG-01 | Structured logging (JSON); correlation IDs (trace-id) propagated across services | High | ☐ | |
| LOG-02 | Security events logged: auth success/failure, privilege changes, access denied, input validation failures | Critical | ☐ | |
| LOG-03 | No sensitive data in logs (passwords, tokens, PII, credit cards); automated scrubbing | Critical | ☐ | |
| LOG-04 | Log integrity: append-only, tamper-evident (CloudTrail, signed logs, SIEM forward) | High | ☐ | |
| LOG-05 | Retention: ≥1 year hot, ≥7 years cold for audit; compliance-driven | Medium | ☐ | |
| LOG-06 | Alerting: real-time on critical events (brute force, privilege escalation, WAF blocks, anomaly) | Critical | ☐ | |
| LOG-07 | Dashboards: security overview, auth health, error rates, attack patterns | Medium | ☐ | |
| LOG-08 | Incident response plan: documented, tested (tabletop), runbooks for top 10 scenarios | High | ☐ | |
| LOG-09 | Forensic readiness: disk/memory capture automation, chain of custody, legal hold process | Medium | ☐ | |
| LOG-10 | Threat intelligence feed integration: block known bad IPs, domains, ASNs | Medium | ☐ | |

---

## 11. Supply Chain & Dependencies

| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| DEP-01 | SCA scanning in CI (GitHub Dependabot, Snyk, Trivy, OWASP Dependency-Check); fail on Critical/High | Critical | ☐ | |
| DEP-02 | SBOM generated per build; reviewed for license compliance and known vulnerabilities | High | ☐ | |
| DEP-03 | Dependencies pinned to exact versions; lockfiles committed; no floating versions | High | ☐ | |
| DEP-04 | Private registry with proxy; no direct internet pulls in build; integrity verification (hashes) | Medium | ☐ | |
| DEP-05 | Malware/tampering detection: sigstore verification, npm/yarn audit signatures, Reproducible Builds | Medium | ☐ | |
| DEP-06 | Abandoned/unmaintained deps identified; replacement plan or fork with maintenance | Medium | ☐ | |
| DEP-07 | Transitive dependency analysis; minimal dependency tree; tree-shaking where possible | Low | ☐ | |
| DEP-08 | Supply chain threat model documented (SLSA, NIST SSDF); third-party risk assessed | Medium | ☐ | |

---

## 12. Compliance & Privacy

| ID | Check | Priority | Status | Evidence/Notes |
|----|-------|----------|--------|----------------|
| COMP-01 | Data classification: PII, PHI, PCI, secrets identified; handling procedures per class | High | ☐ | |
| COMP-02 | Data minimization: collect only what's needed; purpose limitation enforced | Medium | ☐ | |
| COMP-03 | Encryption at rest/in transit for regulated data (see CRYPTO-03, CRYPTO-04) | Critical | ☐ | |
| COMP-04 | Access logging for regulated data; quarterly access reviews | High | ☐ | |
| COMP-05 | Data subject rights: export, deletion, rectification automated or ≤30 days | Medium | ☐ | |
| COMP-06 | DPA/BAA with all subprocessors; international transfer mechanisms (SCCs, adequacy) | Medium | ☐ | |
| COMP-07 | Privacy by design: DPIA for new features; privacy review in SDLC | Medium | ☐ | |
| COMP-08 | Cookie consent: GDPR/ePrivacy compliant; granular controls; no dark patterns | Medium | ☐ | |
| COMP-09 | Breach notification process: ≤72 hours (GDPR); tested communication templates | High | ☐ | |

---

## 13. Audit Execution Guide

### 13.1 Methodology
1. **Reconnaissance** — Map attack surface: endpoints, tech stack, data flows, trust boundaries
2. **Automated Scanning** — SAST, DAST, SCA, container scan, IaC scan; triage findings
3. **Manual Review** — Business logic flaws, authz, crypto implementation, architecture review
4. **Penetration Testing** — Authenticated and unauthenticated; scope agreed in writing
5. **Reporting** — Risk-rated findings (Critical/High/Medium/Low/Info) with evidence, PoC, remediation
6. **Retest** — Verify fixes; regression test

### 13.2 Tooling Baseline (suggested)
| Category | Tools |
|----------|-------|
| SAST | Semgrep, CodeQL, SonarQube, language-specific linters |
| DAST | OWASP ZAP, Burp Suite Pro, Nuclei templates |
| SCA | Trivy, Grype, Dependabot, Snyk, OSV-Scanner |
| Container | Trivy, Grype, Docker Scout, Syft (SBOM) |
| IaC | Checkov, tfsec, Terrascan, KICS |
| Secrets | TruffleHog, Gitleaks, detect-secrets |
| API | Postman/Newman, Schemathesis, Dredd |

### 13.3 Scoring & SLA
| Severity | SLA (Remediation) | Example |
|----------|-------------------|---------|
| Critical | 24–72 hours | RCE, auth bypass, data exfiltration |
| High | 7–14 days | SQLi, IDOR, broken crypto, SSRF |
| Medium | 30–60 days | XSS (stored/reflected), CSRF, info disclosure |
| Low | 90 days | Missing headers, version disclosure, weak CSP |
| Info | Next sprint | Best practice gaps, hardening opportunities |

### 13.4 Sign-Off
| Role | Name | Signature | Date |
|------|------|-----------|------|
| Security Architect | | | |
| Engineering Lead | | | |
| Product Owner | | | |
| Compliance/Privacy | | | |

---

## Appendix A: Quick Reference — Top 20 Must-Fix Patterns

1. **No parameterized queries** → SQL/NoSQL injection
2. **No output encoding / CSP** → XSS
3. **No CSRF tokens / SameSite** → CSRF
4. **JWT `none` alg or weak secret** → Token forgery
5. **Secrets in code/repo** → Supply chain compromise
6. **No rate limiting on auth** → Credential stuffing
7. **IDOR / no object-level authz** → Horizontal privilege escalation
8. **File upload without validation** → RCE via webshell
9. **Deserialization of untrusted data** → RCE
10. **SSRF (metadata service access)** → Cloud credential theft
11. **Broken TLS / cert validation** → MitM
12. **Default credentials / debug endpoints** → Unauthorized access
13. **Missing security headers** → Clickjacking, MIME sniffing, etc.
14. **Logging PII/secrets** → Data leakage
15. **No MFA for admin** → Account takeover
16. **Vulnerable dependencies unpatched** → Known exploit
17. **Insecure CORS** → Cross-origin data theft
18. **Race conditions (TOCTOU)** → Business logic bypass
19. **Weak password reset** → Account takeover
20. **No incident response plan** → Extended breach impact

---

## Appendix B: Trust Boundary Diagram (Template)

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET (Untrusted)                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │ TLS 1.3, WAF, Rate Limit, DDoS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EDGE / API GATEWAY (DMZ)                     │
│  AuthN (OIDC), AuthZ (PDP), Schema Validation, Throttling      │
└─────────────────────────────┬───────────────────────────────────┘
                              │ mTLS, Service Mesh
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  APP TIER        │ │  APP TIER        │ │  APP TIER        │
│  (Stateless)     │ │  (Stateless)     │ │  (Stateless)     │
│  Input Valid,    │ │  Input Valid,    │ │  Input Valid,    │
│  Output Encode,  │ │  Output Encode,  │ │  Output Encode,  │
│  AuthZ Checks    │ │  AuthZ Checks    │ │  AuthZ Checks    │
└────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │ mTLS, Least Privilege
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  DATA TIER       │ │  CACHE/SESSION   │ │  EXTERNAL APIS   │
│  (Encrypted,     │ │  (Encrypted,     │ │  (Signed,        │
│   Audited,       │ │   TTL, Auth)     │ │   Validated,     │
│   Row-Level Sec) │ │                  │ │   Allow-listed)  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

---

*End of Checklist*  
*Review quarterly or after major architecture changes*