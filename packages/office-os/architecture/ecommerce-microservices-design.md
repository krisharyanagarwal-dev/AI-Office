# E-Commerce Platform — Microservices Architecture Design

**Task ID:** 1727a1bd · **Status:** design artifact · **Date:** 2026-11-05
**Assumption (stated, not blocking):** greenfield B2C e-commerce platform on cloud/Kubernetes, one product team owning all five components, order volume starting at hundreds/day scaling to millions/day. No legacy system to preserve.

---

## 1. Bounded Contexts (drawn from business language, not org chart)

| Bounded Context | Business language it owns | Service |
|---|---|---|
| **Identity & Access** | customer, account, credentials, session, token | Auth Service |
| **Catalog** | product, SKU, price, inventory, category | Product Catalog Service |
| **Ordering** | cart, checkout, order, order line, order status | Order Service |
| **Payments** | payment, charge, refund, transaction, PSP reference | Payment Service |

**API Gateway is infrastructure, not a bounded context.** It routes, authenticates at the edge, rate-limits, and aggregates — it owns no business language.

### Context map

```
                 ┌──────────────┐
   Client ─────▶│ API Gateway  │────▶ Auth Service      (token issue/validate, sync)
                 │  (edge: TLS, │────▶ Catalog Service   (product/SKU reads, sync)
                 │   rate limit,│────▶ Order Service     (cart/checkout/orders, sync)
                 │   routing)   │────▶ Payment Service   (charge/refund intent, sync)
                 └──────────────┘
                        │
                        ▼  async events (message broker)
              Order Service ──OrderPlaced──▶ Catalog (reserve inventory), Payment (authorize)
              Payment Service ──PaymentCaptured──▶ Order (confirm), Catalog (decrement stock)
              Payment Service ──PaymentFailed──▶ Order (cancel/hold)
```

**Direction rule:** business events flow *out of* the context that owns the fact; consumers react, they never reach back in to mutate another context's data. The only cross-context writes happen through events + local reaction.

---

## 2. Module Contracts (what crosses each boundary)

Each contract is versioned and owned by the producing context.

### Auth Service → all services (and gateway)
- **Sync:** `POST /auth/introspect` (gateway validates JWT locally via JWKS; introspection only as fallback), `POST /auth/token`, `POST /auth/refresh`, `POST /auth/revoke`.
- **Events:** `CustomerRegistered`, `CustomerDeactivated`.
- **Contract:** JWT (RS256) with short TTL (15 min) + refresh token (30 days, rotating, stored hashed). Scopes per service (`catalog:read`, `orders:write`, `payments:write`).

### Product Catalog Service
- **Sync (via gateway):** `GET /products`, `GET /products/{id}`, `GET /skus/{sku}/availability`, `POST /products` (admin), `PUT /prices` (admin).
- **Events consumed:** `OrderPlaced` → reserve stock (idempotent, keyed by orderId); `PaymentCaptured` → confirm decrement; `PaymentFailed`/`OrderCancelled` → release reservation.
- **Events published:** `StockReserved`, `StockReleased`, `PriceChanged`.
- **Contract:** availability is **eventually consistent** — checkout uses reservation, not raw count, to avoid oversell.

### Order Service
- **Sync (via gateway):** `POST /cart`, `POST /checkout` → creates order in `PENDING_PAYMENT`, `GET /orders/{id}` (owner-scoped), `POST /orders/{id}/cancel`.
- **Events published:** `OrderPlaced`, `OrderConfirmed`, `OrderCancelled`, `OrderCompleted`.
- **Events consumed:** `PaymentCaptured` → confirm order; `PaymentFailed` → cancel + trigger stock release.
- **Contract:** order is the **aggregate root** of the ordering context; order lines are immutable once placed except status transitions.

### Payment Service
- **Sync (via gateway):** `POST /payments/authorize`, `POST /payments/{id}/capture`, `POST /payments/{id}/refund`. Never stores full card data — tokenized at PSP; we store only PSP reference + last4 + status.
- **Events published:** `PaymentAuthorized`, `PaymentCaptured`, `PaymentFailed`, `RefundIssued`.
- **Contract:** payment states are a strict state machine: `CREATED → AUTHORIZED → CAPTURED → (REFUNDED)` or `→ FAILED`. Refunds only against `CAPTURED`.

### API Gateway contract
- Single entry point; routes `/auth/*`, `/catalog/*`, `/orders/*`, `/payments/*`.
- Terminates TLS, validates JWT signature via JWKS (no call to Auth per request except introspection fallback), enforces per-customer rate limits, request size limits, and emits correlation IDs.
- Does **not** contain business logic, does **not** join data across services (no BFF aggregation logic initially — see reversible decisions).

---

## 3. Communication Patterns

| Interaction | Pattern | Why |
|---|---|---|
| Client → services (queries, commands that need an immediate answer) | **Sync REST over HTTPS through the gateway** | Customer is waiting; latency and error semantics are simple and debuggable. |
| Order → Payment/Catalog after checkout | **Async events via message broker** (Kafka or managed equivalent; at low volume, a transactional outbox on a queue suffices) | Decouples checkout latency from PSP latency; survives Payment downtime. |
| Cross-context business integration (stock, payment status) | **Domain events, at-least-once delivery, consumer-side idempotency** (dedupe key = event ID) | No distributed transactions across services. |
| The checkout business transaction spanning Order + Payment + Catalog | **Saga (choreography via events, not orchestration)** | Simplest pattern that satisfies the constraint: 3 steps, no nested rollback logic. Orchestrator adds a component to maintain for no current need. Compensating actions: `PaymentFailed → cancel order + release stock`. |
| Internal service-to-service calls (rare) | **gRPC only if a proven latency need appears**; default REST | REST first — one protocol to maintain. gRPC is a cheap reversible upgrade per-endpoint, not a platform decision. |

**Reliability rules (apply everywhere):**
- Every async consumer is idempotent (dedupe on event ID).
- **Transactional outbox:** services write events to an outbox table in the same DB transaction as the state change; a relay publishes to the broker. This makes "state changed but event lost" impossible — the classic dual-write problem, solved with one table per service.
- Sync calls get timeouts (default 2s), retries with exponential backoff + jitter **only on idempotent endpoints**, and circuit breakers.
- Correlation ID injected at gateway, propagated on every hop (header + log field + trace span).

---

## 4. Data Strategy

**Rule: database-per-service. No shared databases, no cross-service SQL joins.** Each service owns its schema and may evolve it independently; other services see only its public contract (API + events).

| Service | Store | Rationale |
|---|---|---|
| Auth | PostgreSQL (users, refresh tokens) | Relational integrity for credentials; small, high-security blast radius. |
| Catalog | PostgreSQL (products, SKUs, prices) + Redis cache for hot product reads | Strong consistency for price/stock writes; cache only for read-heavy product detail. Prices/stock changes invalidate cache via `PriceChanged`/`StockReserved` events. |
| Order | PostgreSQL (orders, lines) | Orders are the system of record for transactions; relational model fits aggregates. |
| Payment | PostgreSQL (payment records, PSP references) | PCI scope minimized: no PAN/CVV ever enters our DB; only references. |
| All | Outbox table per service + broker topics: `orders`, `payments`, `catalog`, `identity` | Reliable event publication. |

**Read models:** none initially. If catalog search needs Elasticsearch later, it is a **derived, rebuildable** read model fed by catalog events — added only when query patterns demand it (reversible: drop and rebuild from events).

**Event sourcing:** deliberately **not** adopted now. Order/payment state machines are simple and current-state PostgreSQL is enough; event sourcing's audit trail is partially covered by the outbox/broker event log. Revisit only if audit or time-travel requirements appear.

**Backups & PII:** per-service snapshots + PITR; customer PII concentrated in Auth and Order — encryption at rest, field-level encryption for payment-adjacent fields, GDPR-style deletion via `CustomerDeactivated` event propagation.

---

## 5. Pattern Rationale (each abstraction justified against maintenance cost)

| Pattern | Satisfies | Maintenance cost accepted |
|---|---|---|
| API Gateway | Single edge: TLS, authn, rate limit, routing | One component to operate; kept thin deliberately — no business logic, or it becomes a God Object. |
| Database per service | Independent deployability, no schema coupling | Eventual consistency between contexts; mitigated by saga + idempotency, not by shared DBs. |
| Saga choreography | Multi-service checkout without 2PC | Compensating actions must be written and tested per failure path (3 paths today). |
| Transactional outbox | Exactly-once-ish event publication | One extra table + relay per service; removes the hardest class of distributed bug. |
| Async events for cross-context | Resilience, decoupling | Event schema versioning discipline; consumers must tolerate duplicates/reordering. |
| JWT at edge, introspection fallback | Low-latency authn on every request | Token revocation is soft (short TTL + denylist for critical revocations). |

**Explicitly rejected now:** CQRS with separate read/write models everywhere, event sourcing, service mesh (replaced by gateway + broker until multi-region or mTLS-between-services is needed), Kubernetes (assume managed containers; infra choice is reversible and orthogonal).

---

## 6. Non-Functional

- **Scaling:** stateless services scale horizontally behind gateway; Payment is the most constrained (PSP rate limits) — queue captures, process async. Catalog reads scale via cache + read replicas. Order DB is the write hotspot — partition by customer or time if needed later.
- **Resilience:** circuit breakers on all sync calls; bulkheads per downstream; graceful degradation: catalog browse works if Payment is down (checkout queues), checkout never blocks on search.
- **Security:** mTLS internal when service mesh arrives; secrets in a manager, never in env files committed to repo; RBAC scopes per service; PCI DSS scope kept to Payment + PSP tokenization.
- **Observability:** structured logs with correlation ID, RED metrics per service (rate/error/duration), distributed tracing (OpenTelemetry), alerting on saga-stuck states (order in `PENDING_PAYMENT` > 15 min = page).

---

## 7. Decisions: Irreversible vs Reversible

### Expensive to reverse — decided now, documented here
1. **Database-per-service; no shared database.** Splitting a shared DB later is the costliest migration in the industry. Cheap to do right now, brutal later.
2. **Event-driven integration between Order/Payment/Catalog (saga), no synchronous chain, no 2PC.** Changing communication topology later means rewriting every integration.
3. **PCI minimization: no card data in our systems, PSP tokenization only.** A breach of stored PAN is existential; this cannot be retrofitted cheaply.
4. **Order Service owns the order aggregate; other services never write order state.** Aggregate ownership prevents split-brain on order status.
5. **API Gateway as the single public entry point.** Exposing services directly later is possible but dissolves the security boundary; treat public ingress as fixed.

### Cheap to reverse — do not over-debate
- Message broker choice (Kafka vs managed queue vs RabbitMQ) — swap behind the outbox interface.
- REST vs gRPC per endpoint; protobuf vs JSON on the wire.
- PostgreSQL vs another relational store per service (all own their schema; migration is per-service).
- Cache strategy (Redis now, alternatives later).
- Adding read models / search index (rebuildable from events).
- Saga choreography → orchestrator if a 4th+ participant or complex compensation appears.
- Container orchestration platform (K8s vs managed) — infra, not architecture.
- BFF layer for mobile if payload-shaping needs emerge.

---

## 8. Next Steps

1. Stand up gateway + Auth first (everything depends on identity); define JWKS + scope model.
2. Implement Order Service with outbox + `OrderPlaced` event; Payment Service with PSP sandbox; Catalog reservation consumer. Prove the saga end-to-end in staging with fault injection (kill Payment mid-checkout → verify compensating cancel + stock release).
3. Define event schema registry (versioned schemas, compatibility rules: additive-only v1).
4. Load-test the checkout path; measure p99; only then tune caches/replicas.
5. Write the runbook for stuck sagas (`PENDING_PAYMENT` timeout sweeper) before launch — this is the #1 production incident class in this design.
6. Revisit rejected patterns (CQRS read models, service mesh, event sourcing) at 10x current load or when audit requirements change — not before.
