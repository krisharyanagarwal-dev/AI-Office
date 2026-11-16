# E-Commerce Platform — Microservices Architecture Design

**Task ID:** 9671c7a7 · **Status:** design artifact · **Date:** 2026-11-05 · **Agent:** software-architect

**Assumption (stated, not blocking):** greenfield B2C e-commerce platform, cloud-hosted, managed containers (Kubernetes or equivalent), one product team owning all five components. Traffic starts at hundreds of orders/day and must scale to millions/day. No legacy system to preserve.

---

## 1. Bounded Contexts (drawn from business language, not the org chart)

| Bounded Context | Business language it owns | Component |
|---|---|---|
| **Identity & Access** | customer, account, credentials, session, token | Auth Service |
| **Catalog** | product, SKU, price, inventory, category | Product Catalog Service |
| **Ordering** | cart, checkout, order, order line, order status | Order Service |
| **Payments** | payment, authorization, capture, refund, PSP reference | Payment Service |

**The API Gateway is infrastructure, not a bounded context.** It routes, terminates TLS, authenticates at the edge, and rate-limits. It owns no business language and must stay that way.

### Context map

```
                 ┌──────────────┐
   Client ─────▶│ API Gateway  │────▶ Auth Service       (token issue/validate, sync)
                 │ (edge: TLS,  │────▶ Catalog Service    (product/SKU reads, sync)
                 │  rate limit, │────▶ Order Service      (cart/checkout/orders, sync)
                 │  routing)    │────▶ Payment Service    (authorize/capture/refund, sync)
                 └──────────────┘
                        │
                        ▼  async domain events (message broker)
   Order Service ──OrderPlaced──────▶ Catalog (reserve stock), Payment (authorize)
   Payment Service ──PaymentCaptured─▶ Order (confirm), Catalog (decrement stock)
   Payment Service ──PaymentFailed──▶ Order (cancel/hold), Catalog (release stock)
```

**Direction rule:** events flow *out of* the context that owns the fact. Consumers react; they never reach back in to mutate another context's data. The only cross-context writes happen via events + local reaction. No distributed transactions, ever.

---

## 2. Module Contracts (what crosses each boundary, and in which direction)

All contracts are versioned and owned by the producing context. Additive changes only in v1 (see §7).

### API Gateway (edge contract — inbound only)
- Single public entry point. Routes `/auth/*`, `/catalog/*`, `/orders/*`, `/payments/*`.
- Terminates TLS; validates JWT signatures locally against Auth's JWKS (no Auth call on the hot path; introspection only as fallback for revocation checks).
- Enforces per-customer rate limits, request-size limits; injects a correlation ID on every request.
- Contains **no business logic and no cross-service data joins**. (No BFF initially — reversible, see §7.)

### Auth Service → all services + gateway
- **Sync:** `POST /auth/token` (login), `POST /auth/refresh` (rotating refresh), `POST /auth/revoke`, `POST /auth/introspect` (fallback). JWKS endpoint for gateway key fetch.
- **Events:** `CustomerRegistered`, `CustomerDeactivated`.
- **Contract:** access JWT (RS256, 15-min TTL) + refresh token (30-day, rotating, stored only as a hash). Scopes per audience: `catalog:read`, `orders:read|write`, `payments:write`, `admin:*`. Revocation of an access token is soft (short TTL); critical revocations go on a denylist checked at introspection.

### Product Catalog Service
- **Sync (via gateway):** `GET /products`, `GET /products/{id}`, `GET /skus/{sku}/availability`, admin `POST /products`, `PUT /prices`.
- **Consumes:** `OrderPlaced` → reserve stock (idempotent on orderId); `PaymentCaptured` → confirm decrement; `PaymentFailed` / `OrderCancelled` → release reservation.
- **Publishes:** `StockReserved`, `StockReleased`, `PriceChanged`.
- **Contract:** availability is **eventually consistent** — checkout relies on reservation, not a raw count, so oversell is structurally impossible.

### Order Service
- **Sync (via gateway):** `POST /cart`, `POST /checkout` → order created in `PENDING_PAYMENT`, `GET /orders/{id}` (owner-scoped), `POST /orders/{id}/cancel`.
- **Publishes:** `OrderPlaced`, `OrderConfirmed`, `OrderCancelled`, `OrderCompleted`.
- **Consumes:** `PaymentCaptured` → confirm; `PaymentFailed` → cancel and trigger stock release.
- **Contract:** the **order is the aggregate root** of the ordering context. Order lines are immutable once placed; only status transitions are allowed. No other service ever writes order state.

### Payment Service
- **Sync (via gateway):** `POST /payments/authorize`, `POST /payments/{id}/capture`, `POST /payments/{id}/refund`.
- **Publishes:** `PaymentAuthorized`, `PaymentCaptured`, `PaymentFailed`, `RefundIssued`.
- **Contract:** strict state machine `CREATED → AUTHORIZED → CAPTURED → (REFUNDED)` or `→ FAILED`. Refunds only against `CAPTURED`. **PCI minimization:** card data is tokenized at the PSP and never touches our systems; we store only PSP reference, last4, amount, status. This boundary is irreversible-by-breach (see §7).

---

## 3. Communication Patterns

| Interaction | Pattern | Why this and not the alternative |
|---|---|---|
| Client → services (queries and commands that need an immediate answer) | **Sync REST/HTTPS through the gateway** | The customer is waiting; latency and error semantics are simple and debuggable. |
| Order → Catalog/Payment after checkout | **Async domain events over a message broker** (Kafka or managed equivalent; at low volume a queue + outbox suffices) | Decouples checkout latency from PSP latency; survives Payment downtime. |
| Cross-context business integration (stock, payment status) | **Domain events, at-least-once delivery, consumer-side idempotency** (dedupe key = event ID) | Avoids distributed transactions entirely. |
| The multi-service checkout business transaction (Order + Payment + Catalog) | **Saga via choreography (events), not orchestration** | Simplest pattern that fits: 3 steps, no nested rollback logic. An orchestrator is an extra component to maintain for no current need. Compensations: `PaymentFailed → cancel order + release stock`. |
| Rare internal service-to-service calls | **REST by default; gRPC only if a proven latency need appears** | One protocol to maintain. gRPC per-endpoint is a cheap reversible upgrade, not a platform decision. |

**Reliability rules (apply everywhere):**
- Every async consumer is idempotent (dedupe on event ID) — duplicates and reordering are normal, not exceptional.
- **Transactional outbox:** each service writes events to an outbox table in the *same DB transaction* as the state change; a relay publishes to the broker. "State changed but event lost" becomes impossible. This is the one non-negotiable reliability mechanism.
- Sync calls: 2s default timeout, retry with exponential backoff + jitter **only on idempotent endpoints**, circuit breaker per downstream.
- Correlation ID injected at the gateway, propagated on every hop (header + log field + trace span).

---

## 4. Data Strategy

**Rule: database-per-service. No shared databases, no cross-service SQL joins.** Each service owns its schema and evolves it independently; other services see only its public contract (API + events).

| Service | Store | Rationale |
|---|---|---|
| Auth | PostgreSQL (users, hashed refresh tokens) | Relational integrity for credentials; small, high-security blast radius. |
| Catalog | PostgreSQL (products, SKUs, prices, reservations) + Redis cache for hot product reads | Strong consistency on price/stock writes; cache only read-heavy product detail, invalidated by `PriceChanged`/`StockReserved`. |
| Order | PostgreSQL (orders, order lines, outbox) | Orders are the system of record for the transaction; the relational aggregate model fits. |
| Payment | PostgreSQL (payment records, PSP references, outbox) | PCI scope minimized: no PAN/CVV ever in our DB. |
| All services | Outbox table per service + broker topics `orders`, `payments`, `catalog`, `identity` | Reliable event publication (§3). |

**Read models:** none initially. If catalog search later needs Elasticsearch, it is a **derived, rebuildable** read model fed by catalog events — added only when query patterns demand it, and reversible (drop and rebuild from events).

**Event sourcing: deliberately not adopted.** Order/payment state machines are simple; current-state PostgreSQL plus the outbox/broker log covers the audit need. Revisit only if strict audit or time-travel requirements appear.

**Backups & PII:** per-service snapshots + point-in-time recovery. Customer PII concentrates in Auth and Order: encryption at rest, field-level encryption for sensitive fields, and deletion propagated via `CustomerDeactivated`.

---

## 5. Pattern Rationale (each abstraction justified against its ongoing maintenance cost)

| Pattern | Constraint it satisfies | Maintenance cost accepted |
|---|---|---|
| API Gateway | Single edge for TLS, authn, rate limiting, routing | One component to operate; kept thin deliberately — business logic in the gateway becomes a God Object. |
| Database per service | Independent deployability, no schema coupling | Eventual consistency between contexts; mitigated by saga + idempotency, never by shared DBs. |
| Saga choreography | Multi-service checkout without 2PC | Compensating actions written and tested per failure path (3 today). |
| Transactional outbox | Reliable event publication | One extra table + relay per service; removes the hardest class of distributed bug (dual-write). |
| Async events for cross-context | Resilience and decoupling | Event schema versioning discipline; consumers tolerate duplicates/reordering. |
| JWT at edge, introspection fallback | Low-latency authn per request | Soft revocation (short TTL + denylist for critical cases). |

**Explicitly rejected for now:** CQRS read/write models everywhere, event sourcing, service mesh (gateway + broker suffice until multi-region or inter-service mTLS is needed), BFF layer (add only if mobile payload-shaping needs emerge).

---

## 6. Non-Functional Requirements

- **Scaling:** all services stateless → scale horizontally behind the gateway. Payment is the most constrained (PSP rate limits) → queue captures, process async. Catalog reads scale via cache + read replicas. Order DB is the write hotspot → partition by customer or time only if measurements demand it.
- **Resilience:** circuit breakers and bulkheads on all sync calls. Graceful degradation: catalog browsing works if Payment is down (checkout queues); checkout never blocks on search.
- **Security:** RBAC scopes per service; secrets in a manager, never in committed env files; PCI DSS scope confined to Payment + PSP tokenization; internal mTLS when a service mesh arrives.
- **Observability:** structured logs with correlation ID; RED metrics per service; distributed tracing (OpenTelemetry); alert on saga-stuck states — an order in `PENDING_PAYMENT` > 15 min pages someone. That sweeper runbook is written **before launch**, because stuck sagas are the #1 incident class in this design.

---

## 7. Decisions: Irreversible vs Reversible

### Expensive to reverse — decided now, documented here
1. **Database-per-service; no shared database.** Splitting a shared DB later is the costliest migration in the industry. Cheap to do right now, brutal later.
2. **Event-driven integration between Order/Payment/Catalog (saga), no synchronous chain, no 2PC.** Changing the communication topology later means rewriting every integration.
3. **PCI minimization: no card data in our systems, PSP tokenization only.** Stored-PAN breach is existential and cannot be retrofitted cheaply.
4. **Order Service owns the order aggregate; no other service writes order state.** Prevents split-brain on order status.
5. **API Gateway as the single public entry point.** Exposing services directly dissolves the security boundary; treat public ingress as fixed.
6. **Event schema compatibility rule: additive-only changes in v1** (schema registry enforced). Breaking event contracts silently corrupts every consumer.

### Cheap to reverse — do not over-debate these
- Message broker choice (Kafka vs managed queue vs RabbitMQ) — swapped behind the outbox interface.
- REST vs gRPC per endpoint; JSON vs protobuf on the wire.
- PostgreSQL vs another relational store per service (each owns its schema; migration is per-service).
- Cache technology (Redis now, alternatives later).
- Adding read models / search index (rebuildable from events).
- Saga choreography → orchestrator if a 4th+ participant or complex compensation appears.
- Container orchestration platform (K8s vs managed) — infrastructure, not architecture.
- BFF layer for mobile if payload-shaping needs emerge.

---

## 8. Next Steps

1. Stand up gateway + Auth first (everything depends on identity); define the JWKS and scope model.
2. Implement Order Service with outbox + `OrderPlaced`; Payment Service against the PSP sandbox; Catalog reservation consumer. Prove the saga end-to-end in staging with fault injection (kill Payment mid-checkout → verify compensating cancel + stock release).
3. Set up the event schema registry with additive-only compatibility rules.
4. Write the stuck-saga sweeper runbook (`PENDING_PAYMENT` timeout) before launch.
5. Load-test the checkout path; measure p99; only then tune caches and replicas.
6. Revisit rejected patterns (CQRS read models, service mesh, event sourcing) at 10x current load or when audit requirements change — not before.
