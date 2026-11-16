# Distributed API Rate Limiter (Redis) — Architecture Decision Record

**Task ID:** b830f2b1 (= office-os task 726f736f) · **Status:** design artifact · **Date:** 2026-11-05
**Assumption (stated, not blocking):** no SLOs were given, so I assume an API gateway fronting services, peak 10k RPS, p99 added-latency budget of 5 ms for the limit check, a 99.99% availability target for the limit decision, and a Redis Cluster (≥ Redis 7) deployable in the same AZs as the gateways. Replace the numbers in §6 with measured values when available.

---

## 1. Binding constraint

The limiter sits on the hot path of **100% of requests**, so the binding constraint is **correctness of the allow/deny decision under partial failure, within a p99 latency budget** — not throughput (10k RPS is trivial for Redis) and not cost. In CAP terms: under a Redis partition we must pick per route class between consistency (fail closed — the limit is still enforced) and availability (fail open). A wrong "allow" is an abuse/SLO breach; a slow check taxes every request. We choose **fail closed by default** for authenticated and mutating routes, with a bounded degraded-local mode (§5). Cost is tracked but is not the driver.

---

## 2. Algorithm choice — decision record

| Option | Memory per key | Redis round trips | Exactness | Burst behavior | Verdict |
|---|---|---|---|---|---|
| Fixed window counter | O(1) | 1 (INCR + EXPIRE, or Lua) | 2x over-admission at window boundary | hard cutoff at boundary | Rejected (see revival) |
| Sliding window log | O(window size × limit) | 1 (Lua) | exact | natural | Rejected — memory explodes at high per-key rates |
| Sliding window counter (weighted) | O(2 keys) | 1 (Lua) | approximate (bounded error) | smooth-ish | Rejected — approximation where exactness is cheap |
| **Token bucket, atomic Lua script** | **O(1): 2 fields + TTL** | **1 (EVALSHA)** | **exact** | **configurable burst = capacity** | **Chosen** |

**Chosen: token bucket in a single atomic Lua script.** One Redis key per limiter, state = `{tokens: float, ts: ms}`. Capacity = allowed burst; refill is continuous at `rate` tokens/sec. Lua is required because check-and-decrement must be atomic across all gateway instances; Redis executes each script atomically, so there is no WATCH/MULTI race and no double-spend of tokens.

**Rejected alternatives and their revival conditions:**
- **Sliding window log** — revive if per-key windows are small (< ~1,000 entries) *and* exact per-interval accounting is required, e.g. contractual per-second billing tiers. Cost: memory O(limit × window) per key.
- **Sliding window counter** — revive if the managed Redis forbids `EVAL`/`EVALSHA` (some do). Needs 2 keys per window; error is bounded but nonzero at boundaries.
- **Fixed window** — revive only for coarse, analytics-grade limiting (internal dashboards, webhooks) where a 2x burst at the boundary is acceptable.
- **Client-side limiting** — never acceptable for enforcement (trivially bypassed); keep only as a courtesy hint in SDKs.
- **Database-backed (Postgres) limiter** — rejected: it puts row-lock contention on the DB hot path. Revive only below ~100 RPS where Redis is overkill.

---

## 3. Architecture

```
                     ┌──────────────────────────────┐
   Client ────────▶ │  API Gateway (per AZ)        │ ──► backend services
                     │  - auth at edge              │
                     │  - tier-0 local bucket (opt) │
                     │  - Redis client pool         │
                     │    EVALSHA(token_bucket.lua) │
                     └──────────────┬───────────────┘
                                    │ 1 round trip / request
                                    ▼
                     ┌──────────────────────────────┐
                     │  Redis Cluster (same AZs)    │
                     │  3+ shards, primary+replica  │
                     │  per shard, noeviction       │
                     │  key: rl:v1:{api_key}:{route}│
                     └──────────────────────────────┘
```

**Key schema:** `rl:v1:{api_key}:{route_class}`. The `{api_key}` hash tag pins all route classes of one customer to a single cluster slot — no CROSSSLOT errors, and it enables future multi-key operations per customer.

**Script (preloaded at boot via `SCRIPT LOAD`, invoked as EVALSHA):**

```lua
-- KEYS[1] = limiter key
-- ARGV[1] = capacity (burst), ARGV[2] = rate (tokens/sec)
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])

local t        = redis.call('TIME')            -- server time: immune to gateway clock skew
local now      = t[1] * 1000 + math.floor(t[2] / 1000)

local bucket   = redis.call('HMGET', key, 'tokens', 'ts')
local tokens   = tonumber(bucket[1]) or capacity   -- new key starts full
local ts       = tonumber(bucket[2]) or now

local elapsed  = math.max(0, now - ts)
tokens         = math.min(capacity, tokens + elapsed * rate / 1000)

local allowed  = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(1000 * capacity / rate) + 1000)  -- TTL = full refill + 1s

-- {allowed, remaining, retry_after_ms}
return { allowed, math.floor(tokens), math.ceil((1 - tokens) * 1000 / rate) }
```

Gateway maps the reply to headers: `allowed=1` → `X-RateLimit-Limit / -Remaining / -Reset`, pass through; `allowed=0` → `429` + `Retry-After: retry_after_ms`.

**Placement decision:** the gateway runs the script directly against Redis (one network hop total) rather than calling a separate Rate Limit Service. This saves a hop and a service to operate. **Revival condition for a dedicated RLS (e.g. Envoy `ext_authz`):** if the gateway cannot host a Redis client + Lua (managed LB, serverless edge), or if tier-0 local buckets must be coordinated centrally.

**Redis settings that are part of the design, not defaults:** `maxmemory-policy noeviction` — evicting a limiter key is a silent free pass; on OOM the script errors and we fail closed (§5). Limiter traffic goes to **primaries only** (scripts are writes; replica lag is irrelevant but reads-from-replica would be a correctness bug).

---

## 4. Edge cases

- **Burst sizing:** `capacity = burst_multiplier × rate` (default 2x) so legitimate spikes are absorbed without 429s.
- **New/unknown key starts full** — allows the initial burst; document it. Flip to start-empty only for strict onboarding tiers.
- **Clock skew:** solved by `redis.call('TIME')` inside the script (safe on Redis ≥ 5 effects-based replication; we require ≥ 7). Client clock only affects the displayed `Retry-After`. On Redis < 5, pass gateway epoch-ms as ARGV and accept ±NTP skew — negligible at these rates.
- **Hot key** (one viral customer hammering a single shard): tier-0 in-process token bucket per key in the gateway, set to 0.5x the global rate, so Redis sees ≤ ~2 checks/sec per hot key. Off by default; **revive when any single key exceeds ~1k RPS** (watch via `SLOWLOG`/latency percentiles).
- **Key cardinality / memory:** one small hash (~100 B) per (api_key × route_class) with TTL. Bound = number of active keys, not request volume. 1M active keys ≈ 100–200 MB; 100M ≈ 10–20 GB — size shards from measured cardinality, monitor `DBSIZE` and `--bigkeys`.
- **Resharding / slot migration:** a key mid-migration can read as absent → initializes full → over-admission bounded by `capacity` per key during the move. Accepted; measured in chaos tests (§7).
- **Multi-route checks in one request:** one EVALSHA with several KEYS is legal in Cluster because the hash tag puts them in one slot.
- **NOSCRIPT** (e.g. after failover to a promoted replica): keep the SHA per connection; on `NOSCRIPT` retry once with `EVAL`, then re-cache.
- **Cluster redirects:** client handles `MOVED`/`ASK`; count them as limiter errors in metrics (they add latency).
- **Client retries re-consume a token** — correct: the retry did hit the API. Document in API docs so clients don't treat 429-retry as free.
- **Float precision:** Lua doubles are exact enough at token magnitudes ≤ 1e6; no drift concern.

---

## 5. Failure modes and behavior under failure

| Failure | Behavior | Rationale |
|---|---|---|
| Single primary down → replica promoted | ~sub-second errors, then normal; NOSCRIPT handled | Cluster self-heals; scripts rerun on new primary |
| Redis unreachable from gateway (partition, full outage) | **Degraded-local for ≤ 30 s, then fail closed (429/503)** | Gateway keeps a per-key local token bucket seeded from the last successful Redis reply (remaining + rate), TTL 30 s, rate × 0.8. Preserves approximate protection through blips without a free pass. |
| Degraded mode exceeded 30 s | **Fail closed** for auth'd/mutating routes; per-route `fail_open: true` allowed only for public read-only endpoints | The limiter exists to stop abuse; availability is Redis Cluster's job (shards + replicas + cross-AZ) |
| Slow Redis (latency spike) | Redis call timeout = 2 ms (p99 budget) → treat as failure → degraded path; circuit breaker opens after 5 failures / 10 s, half-open probes | Protects the request hot path |
| OOM / memory pressure | `noeviction` → write error → treated as failure → degraded/fail-closed + alert at 80% memory | Never evict limiter state |
| `WRONGTYPE` (key namespace collision) | Fail closed + alert | Keys are namespaced `rl:v1:…`; collision means a bug upstream |
| Netsplit gateway-AZ ↔ Redis-AZ | Same as partition: degraded-local → fail closed | Cross-AZ deployment limits blast radius |
| Script bug / unexpected reply | Fail closed + alert | Deny is the safe default for an enforcement component |

**Revival condition for global fail-open:** if the measured cost of rejecting legitimate traffic during an outage exceeds the abuse cost (e.g. a public status page), flip a per-route config flag — never the code path.

---

## 6. Cost model

Per request, marginal cost = **1 Redis command** (~20–50 µs server CPU for this script) + ~180 B on the wire + ~10 µs gateway CPU + one connection from the pool (no connection setup per request).

At the assumed **10k RPS peak** (864M requests/day):
- A modern Redis primary sustains ~100k simple ops/s; a Lua script like this ~50–100k/s single-threaded → 10k RPS is 10–20% of **one** shard. 3 shards × (primary + replica) is ample headroom for failover.
- **Illustrative $ (assumption — replace with your provider's pricing; I don't have it):** at an all-in $0.20/node-hr, 6 nodes = $1.20/hr ≈ **$864/month**. Per request = 864 / (864M × 30) ≈ **$3.3e-8 per request** (~$0.03 per million requests). Cross-AZ traffic is $0 because gateway and Redis share AZs.
- **Formula:** `monthly = nodes × node_hour_price × 730 + monitoring`; `per_request = monthly / (86400 × 30 × avg_RPS)`.
- **Components nobody budgets:** OOM headroom for cardinality (§4), monitoring/alerting (429 rate, limiter p99, degraded-mode seconds, DBSIZE, hot keys), resharding operations, and the Lua script's maintenance. These typically exceed the raw node cost.

**Missing data (and what would produce it):** actual peak/avg RPS and per-key cardinality (2 weeks of gateway logs or a load test), provider Redis pricing (vendor quote), current p99 request latency (APM). Without these, §6 numbers are formulas with illustrative inputs, not quotes.

---

## 7. Verification plan (before rollout)

1. **Correctness:** property-test the Lua script against a single-threaded reference token bucket over randomized arrival traces; assert the count in any window never exceeds `rate × window + capacity`.
2. **Load:** k6/Vegeta at 2x peak; assert added p99 < 2 ms, zero false-allows, expected 429 rate at the limit, no connection churn.
3. **Chaos:** kill a primary (failover), kill the whole cluster, partition a gateway AZ from Redis (iptables); assert degraded-local ≤ 30 s then fail-closed, clean re-sync on recovery, and false-allows during reshard bounded by `capacity`.
4. **Soak:** 7 days at production rates; watch DBSIZE growth, hot keys, OOM alerts, NOSCRIPT/MOVED counters.

---

## 8. Summary of decisions

| # | Decision | Rejected | Revival condition for the rejected option |
|---|---|---|---|
| 1 | Token bucket, atomic Lua, 1 key/limiter, 1 round trip | sliding-window log/counter, fixed window | log: small windows + billing-grade exactness; counter: EVAL forbidden; fixed: analytics-grade only |
| 2 | Gateway-embedded, calls Redis directly | dedicated Rate Limit Service hop | gateway can't host Redis client, or centralized tier-0 required |
| 3 | Fail closed default; degraded-local ≤30 s; per-route fail-open flag for public reads | pure fail-open, pure fail-closed | public read-only route where downtime cost > abuse cost |
| 4 | Server time via `redis.call('TIME')`, Redis ≥ 7 required | client-passed timestamps | Redis < 5 with verbatim replication (accept NTP skew) |
| 5 | `noeviction`, primaries only, hash-tagged keys | eviction policies, replica reads | never for eviction; replica reads never (correctness) |
| 6 | Tier-0 local bucket off by default, 0.5x rate | always-on tier-0 | any key > ~1k RPS (hot-shard protection) |

---

## 9. Next steps

1. Replace §6 assumptions with measured peak RPS, cardinality, and provider pricing.
2. Implement the Lua script + gateway client: EVALSHA with NOSCRIPT→EVAL fallback, MOVED handling, connection pool, 2 ms timeout, circuit breaker, degraded-local buckets.
3. Define the per-route-class config schema: `rate`, `burst`, `fail_open`, tier overrides.
4. Run §7 load + chaos tests; canary on 1% of traffic with false-allow and degraded-mode alerting.
5. Dashboards: 429 rate, limiter p99 latency, Redis error/NOSCRIPT/MOVED counters, degraded-mode seconds, DBSIZE, hot keys.
