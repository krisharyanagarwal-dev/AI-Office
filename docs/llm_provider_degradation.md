# LLM provider degradation: 46 of 58 agents intermittently producing no work

**State:** HANDOFF — every file in the LLM path is claimed by `opencode`.
**Claimed by:** the detecting agent, for this document only.
**Status:** DEGRADED, not a total outage. This is not a "failure storm" claim;
see the measurement discipline note below.

## What is actually happening

Every agent needs an LLM to do work. Across the fleet, all five configured
providers fail, for five different and independent reasons, so an agent that
retries the chain produces `status=llm_error` with `turns=0 tools=0 edits=0`.
No work is done on those attempts. Agents do recover between failures, so the
fleet is not down; it is running at roughly a 29% success rate.

Measured over a 10 minute window across all agent logs:

    agents with log activity        58
    agents hitting total failure   46
    "All LLM providers failed"     756 events
    successful LLM responses       311 events

    success rate = 311 / (756 + 311) = 29%

## Root-cause cluster, not 46 independent bugs

Per root-cause clustering, these are five provider faults, not one fault per
affected agent:

| provider  | failure            | count | interpretation |
|-----------|--------------------|-------|----------------|
| freeHarness | aborted          | 757   | client aborts the call; the server itself is healthy |
| openrouter  | 401 auth         | 611   | no credential configured |
| localai     | 404 not found    | 611   | model name not present on the local runtime |
| nvidia      | 429 too many req | 607   | rate limit |
| groq        | 429 rate limit   | 605   | rate limit |

The services are not down. `free_harness_server.py` has one live process and
answers HTTP 200 on port 8080, and the local runtime has 3 live processes.
So this is an auth, model-availability and rate-limit problem, not an outage.

Two of the five are self-inflicted and systemic rather than a single fault:

1. **openrouter has no credential.** `check_provider_credentials.py` already
   reports `required provider(s) with no credential: openrouter` and explains
   the sharp edge: as a fallback tier it costs nothing, but a model selected
   directly by prefix goes straight to it and fails immediately with 401.
2. **The fleet is saturating its own rate limits.** 56 of 58 agents are
   hitting NVIDIA 429 at the same time. When every agent retries the same
   chain on the same schedule, the aggregate demand is what produces the 429,
   so each agent's retry makes the next agent's retry more likely to fail.

## Measurement discipline

This document does not claim a failure storm. 756 failure events across 46
agents in 10 minutes is request activity plus a 71% failure rate, measured
against a denominator of 1,067 total LLM attempts. The semantic signal that
matters is the executor result, not the volume:

    [F1] executor llm_error All LLM providers failed [attempted: ...]
    [F1] executor finished: status=llm_error turns=0 tools=0 edits=0

`turns=0 tools=0 edits=0` is the proof that no work is being produced. Request
counts alone would not show that.

## Why this is a handoff and not a fix here

`hive/lib/llm/client.js`, `hive/lib/llm/providers.js`,
`scripts/check_provider_credentials.py` and `services/free_harness_server.py`
are all claimed by `opencode`. Editing them would duplicate in-flight work and
risk clobbering a concurrent session, so the fix belongs to that owner.

Two changes would address it, both in the owned path:

- **Backoff and jitter on the retry chain.** Simultaneous retries from 56
  agents are self-amplifying. A per-agent jittered backoff would reduce the
  aggregate rate-limit pressure instead of feeding it.
- **Treat an uncredentialed provider as absent.** If OpenRouter has no key it
  should be removed from the chain rather than attempted and failed 611 times,
  which costs a round trip per attempt and produces misleading "provider
  failed" telemetry.

Restoring the OpenRouter credential is a credential-access action and is
explicitly reserved for the operator, not for an agent.

## Reproduce

    for f in /tmp/*_manager.log; do
      tail -c 25000 "$f"
    done | grep -c "All LLM providers failed"

    for f in /tmp/*_manager.log; do
      tail -c 25000 "$f"
    done | grep -oE "Provider [a-zA-Z]+ failed: .*HTTP [0-9]{3}" | sort | uniq -c | sort -rn

Observed: 2026-09-30, 46/58 agents, 756 failures and 311 successes in 10 min.
