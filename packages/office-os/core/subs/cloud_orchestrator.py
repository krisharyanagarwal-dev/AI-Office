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
import threading
import time
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")
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

# Failover pool order per tier when the primary pool is rate-limited/unavailable.
# The local MLX pool leads every chain: it costs nothing and runs on this Mac.
TIER_FAILOVER_POOLS = {
    "pro": ["mlx_local", "nvidia_key1", "nvidia_key2", "nvidia_key4", "openrouter", "google"],
    "lite": ["mlx_local", "nvidia_key3", "nvidia_key2", "nvidia_key4", "openrouter", "google"],
    "general": ["mlx_local", "nvidia_key3", "nvidia_key2", "nvidia_key4", "openrouter", "google"],
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

    def __init__(self, config_path="/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json"):
        self.router = ProviderRouter(config_path)
        self._consecutive_cloud_failures = 0
        self._cloud_failover_threshold = 3
        self._failover_until = 0
        # Round-robin across all available models so concurrent workers never
        # share the same model (keeps all keys warm, spreads load evenly).
        self._model_rr_index = 0
        self._model_rr_lock = threading.Lock()

    def _failover_pools(self, tier):
        """Return ordered pool list for this tier."""
        return TIER_FAILOVER_POOLS.get(tier, ["mlx_local", "nvidia_key1", "nvidia_key2", "openrouter", "google"])

    def decide_model(self, agent_info, task_type="exec"):
        """
        Decide which model to use for a task.

        Returns (model_name, pool_name, is_cloud) where:
        - model_name: the model to call
        - pool_name: the provider pool it belongs to
        - is_cloud: True unless the local MLX pool served the task

        Cheapest available pool wins: the local MLX pool costs nothing, so it
        is preferred over the metered cloud pools. Within the cheapest group
        the assignment round-robins, so concurrent workers never share the
        same model.
        """
        agent_id = agent_info["agent_id"]
        tier = agent_info["tier"]
        needs_heavy = agent_needs_heavy_model(agent_id)

        # Build combined list of (model, pool_name) from all available pools
        # in this tier's failover chain.
        candidates = []
        for pool_name in self._failover_pools(tier):
            pool = self.router.pools.get(pool_name)
            if not pool:
                continue
            if not self.router.is_available(pool_name):
                continue
            models = pool["models"]
            if needs_heavy:
                # Heavy agents: only heavy-ish models (first model in each pool)
                models = models[:1]
            for model in models:
                candidates.append((model, pool_name))

        if not candidates:
            raise RuntimeError(
                f"No model available for tier={tier} (all pools rate-limited/unavailable)"
            )

        cheapest = min(self._pool_cost(pool_name) for _, pool_name in candidates)
        cheapest_candidates = [
            (model, pool_name) for model, pool_name in candidates
            if self._pool_cost(pool_name) == cheapest
        ]

        # Round-robin pick: concurrent workers get sequential models -> all different
        with self._model_rr_lock:
            model, pool_name = cheapest_candidates[self._model_rr_index % len(cheapest_candidates)]
            self._model_rr_index += 1

        return model, pool_name, pool_name != "mlx_local"

    def _pool_cost(self, pool_name):
        """Relative cost of a pool. 0 = free (local MLX), 1 = metered cloud."""
        return self.router.pools.get(pool_name, {}).get("cost", 1)

    def call_model(self, model, pool_name, prompt, task_id=None, priority="normal",
                   max_tokens=500, temperature=0.7, timeout=None):
        """
        Call a cloud model via ProviderClient.

        Returns (response_text, model_used, pool_name) or raises.
        Timeout defaults to DEFAULT_TIMEOUT (45s) for fail-fast behavior.
        """
        # Jitter: spread out concurrent workers so they don't all hit the same
        # pool simultaneously (thundering herd on rate-limited keys).
        # With 20 parallel workers, wider jitter (0-10s) keeps load off the 4
        # viable NVIDIA keys while OpenRouter/Google recover from daily caps.
        time.sleep(random.uniform(0, 10))

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
            self.router.mark_rate_limited(pool_name)
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
        # Inject the plan into the exec prompt so the exec model knows what to execute.
        exec_prompt_with_plan = f"{exec_prompt}\n\nPLANNED TASK (from planning phase):\n{plan_text}"
        exec_model, exec_pool, _ = self.decide_model(agent_info, task_type="exec")
        try:
            exec_text, exec_model_used, exec_pool_used = self.call_model(
                exec_model, exec_pool, exec_prompt_with_plan,
                task_id=f"{task_id or 'exec'}-exec", priority=priority,
            )
        except Exception as e:
            exec_text, exec_model_used, exec_pool_used = self._call_with_failover(
                agent_info, exec_prompt_with_plan, f"{task_id or 'exec'}-exec", priority,
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
