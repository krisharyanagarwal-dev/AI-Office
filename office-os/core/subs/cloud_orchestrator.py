#!/usr/bin/env python3
"""
Cloud Model Orchestrator - routes tasks between cloud NVIDIA / OpenRouter / Gemini models.

NO local Qwen fallback. Cloud-only fleet routing with per-key failover:

- Pro/heavy agents: NVIDIA nemotron-3-ultra-550b-a55b (key1) -> key2 -> key4 -> OpenRouter/Gemini free
- Lite/general agents: NVIDIA nemotron-3.5-lightning-30b-a3b (key3) -> key2 -> key4 -> OpenRouter/Gemini free

Uses ProviderClient + ProviderRouter for cloud calls with cooldown/rate-limit management.
Fail fast: 45s timeout, retry once on a different key, then mark error and move on.
No DNS gate - per-call results drive key health.
"""

import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/AI-Office/office-os")
from core.provider_client import ProviderClient

PoolUnavailable = ProviderClient.PoolUnavailable
DailyQuotaExceeded = ProviderClient.DailyQuotaExceeded
from core.router import ProviderRouter

# Default fail-fast timeout for cloud calls (seconds)
DEFAULT_TIMEOUT = 45

# Model mapping by tier and task type - cloud only
TIER_MODEL_MAP = {
    "pro": {
        "plan": "nvidia/nemotron-3-ultra-550b-a55b",
        "exec": "nvidia/nemotron-3-ultra-550b-a55b",
    },
    "lite": {
        "plan": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "exec": "nvidia/nemotron-3.5-lightning-30b-a3b",
    },
}

# Preferred pool per tier (router round-robins within pool's model list)
TIER_POOL_MAP = {
    "pro": "nvidia_key1",   # nemotron-3-ultra-550b + deepseek-v4.1-flash
    "lite": "nvidia_key3",  # nemotron-3.5-lightning-30b + nano-omni
}

# Failover pool order per tier when the primary pool is rate-limited/unavailable
TIER_FAILOVER_POOLS = {
    "pro": ["nvidia_key1", "nvidia_key2", "nvidia_key4", "openrouter", "google"],
    "lite": ["nvidia_key3", "nvidia_key2", "nvidia_key4", "openrouter", "google"],
}

# Agent keywords that always need heavy reasoning
HEAVY_AGENT_KEYWORDS = [
    "security", "architect", "trader", "risk", "quant", "penetration",
    "incident", "legal", "counsel", "compliance", "strategy", "business",
    "investment", "chief", "principal",
]


def agent_needs_heavy_model(agent_id):
    """Check if an agent should always use a heavy model regardless of tier."""
    agent_lower = agent_id.lower()
    return any(kw in agent_lower for kw in HEAVY_AGENT_KEYWORDS)


class CloudModelOrchestrator:
    """
    Orchestrates model selection across free cloud providers only.

    Strategy:
    1. Try primary pool for tier (NVIDIA nemotron)
    2. On failure, retry once on next pool in failover chain (OpenRouter/Gemini free)
    3. If all cloud calls fail, raise so JEV marks the task 'error' and moves on
    - Local Qwen is NOT used for fleet tasks (cloud-only per policy)
    - No DNS gate - real call results drive key health
    """

    def __init__(self, config_path="/Users/aryanagarwal/AI-Office/office-os/config/office.json"):
        self.router = ProviderRouter(config_path)
        self._consecutive_cloud_failures = 0
        self._cloud_failover_threshold = 3
        self._failover_until = 0

    def _failover_pools(self, tier):
        """Return ordered pool list for this tier."""
        return TIER_FAILOVER_POOLS.get(tier, ["nvidia_key1", "nvidia_key2", "openrouter", "google"])

    def decide_model(self, agent_info, task_type="exec"):
        """
        Decide which model to use for a task.

        Returns (model_name, pool_name, is_cloud) where:
        - model_name: the model to call
        - pool_name: the provider pool it belongs to
        - is_cloud: always True (cloud-only fleet)
        """
        agent_id = agent_info["agent_id"]
        tier = agent_info["tier"]
        needs_heavy = agent_needs_heavy_model(agent_id)

        # Primary pool for tier
        primary_pool = TIER_POOL_MAP.get("pro" if needs_heavy or tier == "pro" else "lite", "nvidia_key1")

        # Build ordered pool list: primary first, then failover chain
        pool_order = [primary_pool]
        for p in self._failover_pools(tier):
            if p not in pool_order:
                pool_order.append(p)

        # Fully randomize pool order so concurrent workers don't all hit the
        # same pool first (thundering herd on rate-limited keys). Primary pool
        # stays in the list but its position is randomized — over many calls
        # this spreads load evenly across all available keys.
        random.shuffle(pool_order)

        for pool_name in pool_order:
            pool = self.router.pools.get(pool_name)
            if not pool:
                continue
            if not self.router.is_available(pool_name):
                continue
            models = pool["models"]
            if needs_heavy:
                # Pick the first model in pool (usually the heavy one)
                model = models[0]
            else:
                model = self.router._round_robin_model(pool_name)
            return model, pool_name, True

        # No pool available - caller will treat as error
        raise RuntimeError(f"No cloud pool available for tier={tier} (all pools rate-limited/unavailable)")

    def call_model(self, model, pool_name, prompt, task_id=None, priority="normal",
                   max_tokens=500, temperature=0.7, timeout=None):
        """
        Call a cloud model via ProviderClient.

        Returns (response_text, model_used, pool_name) or raises.
        Timeout defaults to DEFAULT_TIMEOUT (45s) for fail-fast behavior.
        """
        # Jitter: spread out concurrent workers so they don't all hit the same
        # pool simultaneously (thundering herd on rate-limited keys).
        time.sleep(random.uniform(0, 5))

        client = ProviderClient(pool_name, model)
        timeout = timeout or DEFAULT_TIMEOUT

        try:
            response = client.complete(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                priority=priority,
                timeout=timeout,
            )
            self._record_cloud_success()
            self.router.mark_success(pool_name)
            return response, model, pool_name
        except PoolUnavailable as e:
            self.router.mark_rate_limited(pool_name)
            self._record_cloud_failure()
            raise
        except DailyQuotaExceeded as e:
            self.router.mark_daily_quota_exceeded(pool_name)
            self._record_cloud_failure()
            raise
        except Exception as e:
            self._record_cloud_failure()
            raise

    def _record_cloud_failure(self):
        """Track consecutive cloud failures."""
        self._consecutive_cloud_failures += 1
        if self._consecutive_cloud_failures >= self._cloud_failover_threshold:
            self._failover_until = time.time() + 60  # Brief 1-min pause, then try again
            print(f"[orchestrator] Cloud failover pause for 60s "
                  f"({self._consecutive_cloud_failures} consecutive failures)")

    def _record_cloud_success(self):
        """Reset failure counter on successful cloud call."""
        self._consecutive_cloud_failures = 0
        self._failover_until = 0

    def plan_and_execute(self, agent_info, plan_prompt, exec_prompt,
                         task_id=None, priority="normal"):
        """
        Full plan + execute cycle using cloud models with per-key failover.

        Plan: primary pool only (fast path).
        Exec: primary pool, retry on failover chain if needed.

        Returns dict with plan/exec results (text, model, pool, source).
        Raises if both plan and exec fail on all pools.
        """
        agent_id = agent_info["agent_id"]
        tier = agent_info["tier"]
        needs_heavy = agent_needs_heavy_model(agent_id)

        # --- PLAN (primary pool only) ---
        plan_model, plan_pool, _ = self.decide_model(agent_info, task_type="plan")
        try:
            plan_text, plan_model_used, plan_pool_used = self.call_model(
                plan_model, plan_pool, plan_prompt,
                task_id=f"{task_id or 'plan'}-plan", priority=priority,
            )
        except Exception as e:
            # Plan failed - try once on failover chain
            plan_text, plan_model_used, plan_pool_used = self._call_with_failover(
                agent_info, plan_prompt, f"{task_id or 'plan'}-plan", priority,
                skip_pool=plan_pool,
            )
            plan_model = plan_model_used
            plan_pool = plan_pool_used

        # --- EXEC (primary pool, then failover chain) ---
        exec_model, exec_pool, _ = self.decide_model(agent_info, task_type="exec")
        try:
            exec_text, exec_model_used, exec_pool_used = self.call_model(
                exec_model, exec_pool, exec_prompt,
                task_id=f"{task_id or 'exec'}-exec", priority=priority,
            )
        except Exception as e:
            exec_text, exec_model_used, exec_pool_used = self._call_with_failover(
                agent_info, exec_prompt, f"{task_id or 'exec'}-exec", priority,
                skip_pool=exec_pool,
            )
            exec_model = exec_model_used
            exec_pool = exec_pool_used

        return {
            "plan": {
                "text": plan_text,
                "model": plan_model,
                "pool": plan_pool,
                "source": "cloud",
            },
            "exec": {
                "text": exec_text,
                "model": exec_model,
                "pool": exec_pool,
                "source": "cloud",
            },
        }

    def _call_with_failover(self, agent_info, prompt, task_id, priority, skip_pool=None):
        """
        Try ONE failover pool (randomized) — no cascading through all pools.
        A single rate limit shouldn't overload every other key.
        Returns (text, model, pool) on success, raises if the one attempt fails.
        """
        tier = agent_info["tier"]
        needs_heavy = agent_needs_heavy_model(agent_info["agent_id"])
        primary_pool = TIER_POOL_MAP.get("pro" if needs_heavy or tier == "pro" else "lite", "nvidia_key1")

        # Build and shuffle failover candidates (exclude primary + skip_pool)
        candidates = []
        for p in self._failover_pools(tier):
            if p == skip_pool or p == primary_pool:
                continue
            pool = self.router.pools.get(p)
            if not pool:
                continue
            if not self.router.is_available(p):
                continue
            candidates.append(p)

        if not candidates:
            raise RuntimeError(f"No failover pools available for tier={tier}")

        random.shuffle(candidates)
        pool_name = candidates[0]
        pool = self.router.pools[pool_name]
        models = pool["models"]
        model = models[0] if needs_heavy else self.router._round_robin_model(pool_name)

        text, m, p = self.call_model(model, pool_name, prompt, task_id=task_id, priority=priority)
        return text, m, p

    def status(self):
        """Return orchestrator status for monitoring."""
        router_status = self.router.status()
        return {
            "cloud_failover_active": time.time() < self._failover_until,
            "consecutive_cloud_failures": self._consecutive_cloud_failures,
            "default_timeout_sec": DEFAULT_TIMEOUT,
            "provider_pools": router_status,
        }
