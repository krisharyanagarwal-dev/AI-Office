# Distributed API Rate Limiter (Redis) — ADR

**Task ID:** 6d5d24f2 · **Status:** design artifact · **Date:** 2026-11-05
**Consolidates:** `api-rate-limiter-design.md` (task 726f736f) and `distributed-api-rate-limiter-redis.md` (task b830f2b1). Those two artifacts agree on algorithm/architecture and **disagree on the outage policy** (fail-open default vs fail-closed default) — §5 resolves that divergence explicitly.

**Assumption (stated, not blocking):** no SLOs or traffic profile were supplied, so I assume an API gateway fronting services, peak ~10k RPS, p99 added-latency budget ≤ 2 ms for the limit check, per-API-key limits, and Redis ≥ 7 deployable in the same AZs as the gateways. Cost model in §6 is parametric — replace inputs with measured values.

---

## 1. Binding constraint

The limiter sits on the hot path of **100% of requests**, so the binding constraint is **correctness of the allow/deny decision under concurrency (no over-admission beyond configured burst) within a p99 added-latency budget** — not raw throughput (10k RPS is easy for Redis) and not cost. Under a Redis outage there is a genuine CAP choice per route class (fail closed = limit still enforced; fail open = API stays up); §5 makes it an explicit per-route decision instead of a global accident.

---

## 2. Algorithm choice — decision record

All candidates are implementable atomically in one Redis Lua script (one round trip, no check-then-act race). The decision is about semantics and memory, not feasibility.

| Option | Memory/key | Round trips | Exactness | Burst behavior | Verdict |
|---|---|---|---|---|---|
| **Token bucket (atomic Lua)** | O(1): one small hash + TTL | 1 (EVALSHA) | exact w.r.t. bucket semantics | configurable burst = capacity | **Chosen** |
| Sliding window log (ZSET) | O(requests in window) | 1 (Lua) | exact sliding window | natural | Rejected — memory unbounded at high limits |
| Weighted sliding-window counter | O(2 keys) | 1 (Lua) | approximate, can over-admit near boundary | smooth-ish | Rejected — violates the hard-cap constraint |
| Fixed window counter | O(1) | 1 | 2× over-admission at window boundary | hard cutoff | Rejected |
| Local-only / client-side bucket | O(1) | 0 | none globally — N gateways admit N× limit | — | Rejected for enforcement; SDK hint only |

**Chosen: token bucket in a single atomic Lua script** (`architecture/rate-limiter/token_bucket.lua`). One key per limiter, state `{tokens, ts}`, server clock via `redis.call('TIME')` inside the script (immune to gateway clock skew; requires Redis ≥ 5 effects-based replication, we target ≥ 7). Capacity = deliberate burst allowance; refill is continuous. It is the only candidate that is simultaneously exact, O(1) memory, one round trip, and burst-aware ("100 burst, then 10/s").

**Rejected alternatives and their revival conditions:**
- **Sliding window log** → revive for low-rate, high-stakes endpoints (login, password reset, payment initiation; ~5–60 req/min) where exact per-window accounting and an auditable log are worth O(n) memory.
- **Weighted sliding-window counter** → revive if the deployment moves to a managed Redis that forbids `EVAL`/`EVALSHA`, or if a hard cap over *any* rolling window (not bucket semantics) is contractually required.
- **Fixed window** → revive only for analytics-grade internal limiting where a 2× boundary burst is acceptable.
- **redis-cell (GCRA)** → revive if the managed Redis supports modules; GCRA is a cleaner token-bucket equivalent with less script surface. Do not adopt on module-less managed Redis.
- **Database-backed limiter (Postgres)** → rejected (row-lock contention on the DB hot path); revive only below ~100 RPS where Redis is overkill.

---

## 3. Architecture

```
Client ──▶ API Gateway (N stateless instances, per AZ)
              │  auth at edge; limit config cached (1 s refresh)
              │  1× EVALSHA(token_bucket.lua) per request ──┐
              ▼                                            ▼
        backend services                        Redis Cluster (same AZs)
                                               3+ shards, primary+replica each
                                               primaries only, noeviction,
                                               every key TTL'd
                                               key: rl:v1:{api_key}:{route_class}
```

- **Key schema:** `rl:v1:{api_key}:{route_class}` — the `{api_key}` hash tag pins one customer to one cluster slot (no CROSSSLOT; multi-key scripts per customer stay legal).
- **Identity:** API key / tenant ID for authenticated traffic; never raw IP (CGNAT/NAT collapses thousands of users into one bucket). Fall back to `apikey|ip` only pre-auth.
- **One round trip per decision:** check + decrement + TTL refresh in a single EVALSHA; the gateway needs the reply to route, so no pipelining. Added latency ≈ one same-AZ RTT.
- **Placement:** gateway calls Redis directly rather than a dedicated Rate Limit Service — saves a hop and a service. **Revival condition for a dedicated RLS (e.g. Envoy ext_authz):** managed/serverless edge that can't host a Redis client, or centralized tier-0 coordination is required.
- **Limits config:** rate/burst per key served from a gateway-local cache (refreshed ~1/s from a config hash) so the hot path is exactly 1 Redis command; ≤ 2 limiter checks per request to protect the latency budget.
- **Redis policy as part of the design:** `maxmemory-policy noeviction` (evicting a limiter key is a silent free pass; OOM → script errors → §5 policy), writes to primaries only — **never read limiter state from replicas** (stale reads over-admit).
- **Response contract:** allow → pass through with `X-RateLimit-Limit/-Remaining/-Reset`; deny → `429` + `Retry-After` (both computed in the script).
- **Optional tier-0:** in-process bucket per hot key at 0.5× global rate, **off by default**; revive when any single key exceeds ~1k RPS (hot-shard protection). Never cache *remaining allowance* locally in the enforcing path — that over-admits globally. A short-TTL local **deny cache** is allowed (fails toward protection).

---

## 4. Edge cases

| Edge case | Handling |
|---|---|
| Cold/unknown key | Starts **full** (initial burst allowed), atomically inside the script — no race. Document it; start-empty only for strict onboarding tiers. |
| Clock skew | Server time via `redis.call('TIME')` in the script; gateway clock only affects display of `Retry-After`. |
| Key TTL expiry | Semantically safe: expired key = full bucket = natural refill state. Set TTL ≥ 2× `capacity/rate` so expiry only happens after true idle. |
| `NOSCRIPT` after failover/restart | One `EVAL` fallback, re-cache SHA. Count NOSCRIPTs in metrics. |
| Timeout after server executed | **Do not retry** — a retry double-consumes a token. Treat as a fallback-policy event (§5). |
| Cluster MOVED/ASK, resharding | Standard cluster-client redirects; a key mid-migration can read absent → re-initializes full → over-admission bounded by `capacity` per key during the move. Accepted; verified in chaos tests. |
| Hot key (one abusive/viral client) | Alert on single-key QPS; enable tier-0 local bucket (§3). |
| Cardinality / memory | ~100–200 B per *active* key (hash + TTL), not per request. 1M active keys ≈ 100–200 MB; size shards from measured `DBSIZE`; alarm at 70–80% used memory. |
| Client retries | A retried request consumes another token — correct (it did hit the API); document so clients don't treat 429-retries as free. |
| Float precision | Lua doubles are exact enough at token magnitudes ≤ 1e6; no drift concern. |
| Multi-region | One global primary (accept cross-region RTT) **or** per-region approximate limits summing to the global cap — never both silently. Revive per-region if cross-region RTT breaks the p99 budget; document the over-admission bound. |

---

## 5. Failure modes and outage policy (resolves the 726f736f vs b830f2b1 divergence)

The two prior ADRs chose opposite defaults. Resolution: the correct default depends on what the limiter protects, so the policy is **keyed by route class**, not global — with one default:

- **Default (availability-class routes, public reads/GETs): fail open via a degraded local mode** — each gateway runs a per-node token bucket at `rate / N_gateways × 0.8`, seeded from the last successful Redis reply, TTL 30 s. A limiter outage must not take the API down. Every fallback second is metered and alerted, so over-admission during an outage is bounded (≤ capacity + local drift) and **visible**, never silent.
- **Enforcement-class routes (auth, login, payments, billing, scraping targets): fail closed (429/503).** Revival condition to flip the *default*: measured abuse cost during an outage exceeds downtime cost — flip a per-route config flag, never the code path.

| Failure | Behavior |
|---|---|
| Single primary down → replica promoted | Sub-second errors, then normal; NOSCRIPT handled by EVAL fallback |
| Redis unreachable / EVALSHA timeout (> 2 ms) | Degraded-local (availability routes) or 429 (enforcement routes); circuit breaker opens after 5 failures / 10 s, half-open probes |
| Degraded mode > 30 s | Enforcement routes stay closed; availability routes remain degraded with paging alert |
| OOM / memory pressure | `noeviction` → write error → §5 policy + page at 80% memory. Never evict limiter state |
| `WRONGTYPE` (namespace collision) | Fail closed + alert; keys are namespaced `rl:v1:` |
| Script error / malformed reply | Fail closed for that request + alert (deny is the safe default for an enforcement component) |
| Gateway-AZ ↔ Redis-AZ partition | Same as unreachable; cross-AZ Redis deployment limits the blast radius |
| Redis restart (buckets lost) | All clients get a full allowance on restart; acceptable, in the runbook. AOF/RDB shortens but never eliminates the window |

---

## 6. Cost model (parametric — inputs must be measured, not assumed)

**Per request:** 1 EVALSHA (order-of-magnitude 20–50 µs server CPU for this O(1) script — *verify with `redis-benchmark` on the target instance class*) + 1 same-AZ RTT + ~180 B on the wire + ~10 µs gateway CPU from a pooled connection (no per-request connection setup). **Memory is per active key, not per request:** ~100–200 B × active (api_key × route_class) pairs.

**At scale:** let R = RPS, S = shards. Size S so R/S is comfortably within one shard's *measured* command throughput (order of magnitude: ~10⁵ simple ops/s per modern core — a planning figure, not a benchmark; produce the real number with `redis-benchmark -t evalsha` on the chosen instance). At the assumed 10k RPS (864M req/day), one shard runs at ~10–20% utilization; 3 shards × (primary + replica) leaves ample failover headroom.

- **Formulas:** `monthly = nodes × node_hour_price × 730 + monitoring`; `per_request = monthly / (R × 2.63M)`.
- **Illustrative only** (explicit assumption, not a quote): at $0.20/node-hr × 6 nodes ≈ $876/month → ≈ **$1.0e-8 per request** at 10k RPS.
- **Components nobody budgets:** monitoring cardinality (sample limiter metrics ~1% — full per-key metrics at high RPS is a metrics bill, not rounding), OOM headroom for key cardinality, failover/resharding operations, deny-cache memory on gateways, degraded-mode CPU during outages, and Lua script maintenance.
- **Missing data (and what would produce it):** real peak/avg RPS and per-key cardinality (2 weeks of gateway logs or a load test); provider Redis pricing (vendor quote); measured same-AZ RTT distribution (APM); per-shard ops/s (redis-benchmark on the chosen instance class). Until then §6 is formulas with labeled illustrative inputs, not quotes.

---

## 7. Verification plan (before rollout)

1. **Correctness:** property-test the Lua script against a single-threaded reference token bucket over randomized arrival traces; assert admitted count in any window ≤ `rate × window + capacity` (steady state, zero tolerance for false-allows).
2. **Load:** k6/Vegeta at 2× peak; assert added p99 < 2 ms, expected 429 rate at the limit, correct `Retry-After`, no connection churn.
3. **Chaos:** kill a primary (failover), kill the whole cluster, partition a gateway AZ from Redis (iptables); assert degraded-local ≤ 30 s on availability routes, fail-closed on enforcement routes, false-allows during resharding bounded by `capacity`, clean re-sync on recovery.
4. **Soak:** 7 days at production rates; watch DBSIZE growth, hot keys, OOM alerts, NOSCRIPT/MOVED counters.

---

## 8. Summary of decisions

| # | Decision | Rejected | Revival condition for rejected |
|---|---|---|---|
| 1 | Token bucket, one atomic Lua script, 1 hash-tagged key, 1 round trip | sliding-window log / weighted counter / fixed window / local-only | log: low-rate billing-grade endpoints; counter: EVAL forbidden or hard rolling window required; fixed: analytics-grade only; redis-cell: managed Redis with modules |
| 2 | Gateway-embedded, calls Redis directly | dedicated Rate Limit Service hop | gateway can't host Redis client / centralized tier-0 needed |
| 3 | Outage policy keyed by route class; default fail-open + degraded-local (30 s, metered) for availability routes, fail-closed for enforcement routes | global fail-open; global fail-closed | flip default per route via config if abuse cost > downtime cost |
| 4 | Server clock via `redis.call('TIME')`, Redis ≥ 7; `noeviction`; primaries only; TTL ≥ 2× capacity/rate | client-passed timestamps; eviction policies; replica reads | Redis < 5 (accept NTP skew); eviction/replica reads: never |
| 5 | No local allowance cache; local deny cache allowed; tier-0 hot-key bucket off by default | always-on tier-0 | any single key > ~1k RPS |
| 6 | No retry on timeout (double-spend); NOSCRIPT → one EVAL fallback | retry-on-timeout | never — retry would consume 2 tokens |

---

## 9. Files created / updated

- `architecture/rate-limiter/token_bucket.lua` — reference Lua implementation (new).
- `architecture/api-rate-limiter-6d5d24f2.md` — this ADR (consolidates 726f736f + b830f2b1 artifacts).
- `tasks/6d5d24f2.json` — task record marked completed with result.
- `mailbox/outbox_principal-architect.jsonl` — completion notice appended.

## 10. Next steps

1. Replace §6 inputs with measured peak RPS, key cardinality, provider pricing, and a `redis-benchmark` run on the target instance class.
2. Implement the gateway client: EVALSHA with NOSCRIPT→EVAL, MOVED/ASK handling, connection pool, 2 ms timeout, circuit breaker, degraded-local buckets, per-route fail-open/closed config.
3. Define the limit config schema (`rate`, `capacity`, `ttl`, route class, fail posture) and the enforcement-route list with security.
4. Run §7 load + chaos tests; shadow-mode (count would-deny) for 1 week, then canary at 1% with false-allow and degraded-mode alerting.
5. Dashboards/alerts: 429 rate per route, limiter p99 latency, Redis error/NOSCRIPT/MOVED counters, degraded-mode seconds, DBSIZE, used-memory > 80%, single-key hot spots.
