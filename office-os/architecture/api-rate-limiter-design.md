# Distributed API Rate Limiter (Redis) — Architecture Decision Record

**Task ID:** 726f736f · **Status:** design artifact · **Date:** 2026-11-05
**Assumption (stated, not blocking):** API gateway fronts multiple backend services; limiter must enforce a hard per-client cap across N gateway instances; p99 added latency budget ≤ 1 ms per request. Exact traffic profile (RPS, tiers, regions) not yet supplied — cost model below is parametric and must be re-run against real numbers.

---

## 1. Binding constraint

**Hard cap correctness across distributed instances** (no over-admission beyond the configured burst) at **p99 added latency ≤ 1 ms**. Availability posture during Redis outage is a separate, explicit decision (§5), not an afterthought. Cost scales with request count and key cardinality and is modeled in §6.

---

## 2. Algorithm decision

All candidates below are implementable atomically in Redis via a single Lua script (one round trip, no check-then-act race). The decision is about semantics and memory, not feasibility.

| Algorithm | Semantics | Memory per key | Verdict |
|---|---|---|---|
| **Token bucket (chosen)** | Sustained rate `r` + burst up to capacity `C`; exact w.r.t. its own state | O(1) — one small hash | **Chosen** |
| Fixed window counter | Hard cap per wall-clock window, but 2× limit possible at window boundary | O(1) | Rejected — violates hard-cap constraint at boundaries |
| Sliding window log (ZSET of timestamps) | Exact sliding-window cap | O(requests in window) — unbounded at high limits | Rejected for high-RPS public endpoints |
| Weighted sliding-window counter | Approximate; assumes uniform spread in previous window | O(1) | Rejected — can over-admit near boundaries, violating the hard cap |
| Local-only / client-side bucket | None globally | O(1) | Rejected — N gateways each with own bucket admits N× limit |

**Chosen: token bucket, atomic in Lua.** It is the only candidate that is simultaneously exact (w.r.t. bucket semantics), O(1) memory per key, and supports both a sustained rate and a deliberate burst allowance (`capacity`), which products almost always want ("100 burst, then 10/s").

**Rejected alternatives and revival conditions:**
- *Sliding window log* → revives for **low-rate, high-stakes endpoints** (login, password reset, payment initiation; ~5–60 req/min) where exactness and an auditable per-request log are worth O(n) memory.
- *Weighted sliding-window counter* → revives only if a hard cap is relaxed to "approximate cap ±ε" and benchmark shows token bucket Lua is a latency bottleneck (unlikely — both are O(1) Lua).
- *Fixed window* → never; boundary burst is inherent.
- *redis-cell (GCRA module)* → revives if the deployment moves to a managed Redis that supports modules; GCRA is a cleaner token-bucket equivalent with less script surface. Do not adopt on a managed Redis without module support.

### Reference Lua script (token bucket)

```lua
-- KEYS[1] = limiter key (hash-tagged, e.g. "{tenant-123}:bucket")
-- ARGV[1] = capacity (burst), ARGV[2] = refill tokens/sec, ARGV[3] = ttl seconds
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local ttl      = tonumber(ARGV[3])

-- Server-side clock: avoids client clock skew. Redis >= 5 (effects-based
-- replication) permits TIME inside scripts; on older versions pass server time in.
local t   = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)

local b      = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(b[1]) or capacity
local ts     = tonumber(b[2]) or now

local elapsed = math.max(0, now - ts)          -- ms
tokens = math.min(capacity, tokens + elapsed * rate / 1000)

local allowed = tokens >= 1
if allowed then tokens = tokens - 1 end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)

return { allowed and 1 or 0, math.floor(tokens),
         math.ceil((capacity - tokens) / rate * 1000) }  -- allowed, remaining, retry_after_ms
```

Script is O(1) with no loops — it cannot block Redis. Load via `SCRIPT LOAD`, call `EVALSHA`; on `NOSCRIPT` fall back to `EVAL` once.

---

## 3. Architecture

```
Client ──▶ Gateway (N instances, stateless)
              │  1× EVALSHA per request (no read replicas for limiter reads)
              ▼
        Redis Cluster (sharded by hash tag on limiter key)
              │  policy: noeviction, every key TTL'd, alarm at 70% used memory
              ▼
        Metrics (sampled): allowed/denied, fallback events, Redis p99 latency
```

- **Key design:** `{tenant-or-apikey}:{route-class}:bucket` — hash tag keeps each limiter in one cluster slot (no CROSSSLOT, no slot-migration races mid-script).
- **Identity:** API key / tenant ID when authenticated; fall back to `apikey|ip` (not raw IP — NAT/CGNAT collapses thousands of users into one bucket). Never IP alone for authenticated traffic.
- **Single round trip:** decision and state mutation in one EVALSHA. No pipeline (the response is needed to route the request), so added latency ≈ 1 same-AZ RTT to Redis.
- **Tiering:** per-route limits (e.g., `read` 1000/min, `write` 100/min, `auth` 10/min) composed as multiple limiter keys per request when needed — each is a separate key/script call; keep total limiter calls per request ≤ 2 to protect the latency budget.
- **No local allowance cache.** A per-node cache of remaining tokens would over-admit globally. Allowed exception: a short-TTL local **deny cache** for keys Redis recently rejected — it fails toward protection, never toward over-admission.
- **Response contract:** allow → proceed; deny → `429` with `Retry-After` (from script) and headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

---

## 4. Edge cases

| Edge case | Handling |
|---|---|
| Clock skew between gateways | Never trust client time; use `redis.call('TIME')` inside the script |
| Boundary burst | Intended token-bucket behavior: up to `capacity` instantly. Set `capacity` deliberately per tier |
| Key expires mid-flight (TTL) | Bucket recreated full — set TTL ≥ 2× `capacity/rate` so expiry only happens after true idle; document that idle reset = full allowance |
| `NOSCRIPT` after failover/restart | One `EVAL` fallback, then cache the SHA again |
| Timeout after server executed | **Do not retry** — a retry could consume 2 tokens. Treat as fallback-policy event (§5) |
| Redis Cluster MOVED/ASK | Standard cluster client redirect handling; limiter keys are hash-tagged so each key lives in exactly one slot |
| Hot key (one abusive client) | Per-key concurrency cap + local deny cache; alert on single-key QPS |
| Memory growth | `noeviction` + TTL on every key; if memory alarms, eviction of a limiter key = momentary fail-open, so alarm at 70% and page before eviction pressure |
| Multi-region gateways | Decision: one global Redis primary (cross-region RTT accepted) **or** per-region approximate limits that sum to the global cap. Never read limiter state from replicas (stale reads over-admit). Revival condition for per-region: if cross-region RTT breaks the 1 ms p99 budget, accept approximate regional limits and document the over-admission bound |
| CGNAT / shared IPs | Key on API key/tenant, not IP, for authenticated traffic |

---

## 5. Failure modes and availability policy

| Failure | Behavior (chosen) |
|---|---|
| Redis unreachable / EVALSHA timeout | **Default: fail-open with a local per-node token bucket fallback** (approximate — global cap may be exceeded during the outage window), plus a loud metric + alert. **Per-route override to fail-closed (429)** for abuse-sensitive routes (login, payments, scraping targets). Rationale: a limiter outage should not take the API down; silent fail-open is the danger, so the fallback event is always metered |
| Redis process down, restart | Buckets lost → all clients get full allowance on restart. Acceptable; note in runbook. Persistent state (AOF/RDB) only shortens, never eliminates, this window |
| Network partition between gateway and Redis | Same as unreachable; client timeout ~2–5 ms bounds the latency hit before fallback engages |
| Script error / wrong ARGV | Fail-closed for that request (500→429 path logged); config validation at deploy time prevents ARGV drift |
| Lua blocking / latency spike on Redis | Script is O(1); monitor Redis p99 command latency; slowlog review weekly |

---

## 6. Cost model (parametric — re-run with real traffic numbers)

**Per request:**
- Compute: 1 Redis command (EVALSHA), O(1) server CPU — no per-request allocation on the gateway beyond the response headers.
- Latency: +1 same-AZ RTT to Redis (sub-ms to ~1 ms; must be verified against the 1 ms p99 budget with a load test — **missing data: actual RTT distribution on the target instance/network**).
- Memory: ~100–200 bytes per *active* limiter key (one hash + TTL); idle keys expire. Key cardinality = active clients × route classes.

**At scale (formula):** let R = total RPS, S = Redis shards. Each shard sustains ≈ R/S commands/s. Pick S so R/S is comfortably within one shard's measured command throughput (**to be produced by `redis-benchmark` on the chosen instance class — no benchmark numbers are asserted here**). Monthly infra ≈ S × (instance + replica) cost; per-request infra cost ≈ that / (R × 2.6M requests/month). Example with explicit assumption labels: *if* R = 50k RPS and *if* one shard sustains 100k ops/s, then S = 1–2 shards suffice → per-request cost is dominated by the gateway's own CPU, and Redis is < 5% of limiter-path cost. The costs nobody budgets: **monitoring cardinality** (sample limiter metrics at ~1% — full-fidelity per-key metrics at 50k RPS is a metrics bill, not a rounding error), **NOSCRIPT fallback EVALs** (rare), **deny-cache memory** on gateways, and the **fallback token buckets**' CPU during outages.

---

## 7. Decisions made

1. Token bucket (not sliding window of any variant) — exact semantics, O(1) memory, native burst control; single atomic Lua script per limiter key.
2. Server-side Redis clock inside the script; hash-tagged keys for cluster safety; `noeviction` + TTL everywhere.
3. One round trip per limiter decision; ≤ 2 limiter checks per request; no local allowance cache, local deny cache allowed.
4. Failure policy: fail-open with local approximate bucket by default, fail-closed per-route for abuse-sensitive endpoints; fallback always metered. No retries on timeout.
5. Global limit via single Redis primary (or explicitly approximate per-region sums); never read limiter state from replicas.

## 8. Next steps

1. Load-test the Lua script with `redis-benchmark`/a custom harness on the target instance class to get real ops/s per shard and p99 latency — this replaces the parametric cost model.
2. Pull real traffic profile (RPS, distinct API keys, route mix, regions) to size S, key cardinality, and metric sampling rate.
3. Implement the script + gateway integration behind a config flag; shadow-mode (count would-deny, don't deny) for 1 week.
4. Define per-route limits/tiers and the fail-open vs fail-closed route list with the security team.
5. Wire alerts: fallback events, 429 rate per route, Redis p99 latency, used-memory > 70%, single-key hot spots.
6. Decide multi-region posture once cross-region RTT is measured.
