-- token_bucket.lua — atomic token-bucket rate limiter for Redis.
-- Requires Redis >= 5 (effects-based script replication allows redis.call('TIME'));
-- target deployment is Redis >= 7. Script is O(1), no loops: it cannot block Redis.
--
-- Usage: load once at boot with SCRIPT LOAD, invoke with EVALSHA.
--        On NOSCRIPT (e.g. after failover to a fresh primary) fall back to EVAL once.
--        NEVER retry after a timeout — the server may have executed; a retry
--        would consume a second token.
--
-- KEYS[1]  limiter key, hash-tagged so it pins to one cluster slot:
--          "rl:v1:{api_key}:{route_class}"
-- ARGV[1]  capacity      (max burst, in tokens)
-- ARGV[2]  rate_per_sec  (sustained refill rate, tokens/second)
-- ARGV[3]  ttl_ms        (idle expiry; semantically safe: an expired key == full bucket,
--                         so set ttl_ms >= 2 * capacity / rate_per_sec * 1000)
--
-- Returns: { allowed(0|1), remaining, limit, retry_after_ms }

local key        = KEYS[1]
local capacity   = tonumber(ARGV[1])
local rate_per_s = tonumber(ARGV[2])
local ttl_ms     = tonumber(ARGV[3])

-- Server-side clock: immune to gateway/client clock skew.
local t   = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)  -- epoch ms

local bucket = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts     = tonumber(bucket[2])

if tokens == nil or ts == nil then      -- cold key: starts FULL, atomically (no race)
  tokens = capacity
  ts     = now
end

local rate_per_ms = rate_per_s / 1000.0
local elapsed     = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * rate_per_ms)   -- refill, clamped

local allowed     = 0
local retry_after = 0
if tokens >= 1.0 then
  allowed = 1
  tokens  = tokens - 1.0
else
  retry_after = math.ceil((1.0 - tokens) / rate_per_ms)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, ttl_ms)

return { allowed, math.floor(tokens), capacity, retry_after }
