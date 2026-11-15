#!/usr/bin/env python3
"""
Cloud Model Orchestrator - routes tasks between cloud NVIDIA models and local Qwen3.5-9B.

Routes by agent tier and task type:
- Pro agents: try NVIDIA cloud models first (nemotron-3-ultra-550b), fall back to local Qwen
- Lite agents: try NVIDIA lightning model first, fall back to local Qwen
- If cloud DNS/API is unreachable, all agents use local Qwen3.5-9B

Uses ProviderClient + ProviderRouter for cloud calls with cooldown/rate-limit management.
Falls back to local Ollama (port 11434) when cloud is unavailable.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/Users/aryanagarwal/office-os")
from core.provider_client import ProviderClient

PoolUnavailable = ProviderClient.PoolUnavailable
DailyQuotaExceeded = ProviderClient.DailyQuotaExceeded
from core.router import ProviderRouter

LOCAL_MODEL = "hauhaucs/qwen3.5-9b-uncensored-aggressive"
LOCAL_URL = "http://127.0.0.1:11434/v1/completions"

# Model mapping by tier and task type
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

# Preferred pool per tier (router will round-robin within pool's model list)
TIER_POOL_MAP = {
    "pro": "nvidia_key1",   # nemotron-3-ultra-550b + deepseek-v4.1-flash
    "lite": "nvidia_key3",  # nemotron-3.5-lightning-30b + nano-omni
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


def cloud_available():
    """Quick check if cloud DNS resolves (cheap, no API call)."""
    import socket
    try:
        socket.setdefaulttimeout(2)
        socket.gethostbyname("integrate.api.nvidia.com")
        return True
    except (socket.gaierror, socket.timeout, OSError):
        return False
    finally:
        socket.setdefaulttimeout(None)


class CloudModelOrchestrator:
    """
    Orchestrates model selection across cloud NVIDIA providers and local Qwen.

    Priority:
    1. Cloud NVIDIA model (if DNS resolves and provider available)
    2. Local Qwen3.5-9B (always available fallback)
    """

    def __init__(self, config_path="/Users/aryanagarwal/AI-Office/office-os/config/office.json"):
        self.router = ProviderRouter(config_path)
        self.local_url = LOCAL_URL
        self.local_model = LOCAL_MODEL
        self._cloud_dns_checked = False
        self._cloud_dns_ok = False
        self._consecutive_cloud_failures = 0
        self._cloud_failover_threshold = 3  # After 3 failures, skip cloud for a while
        self._failover_until = 0

    def _check_cloud_dns(self):
        """Check cloud DNS once, cache result."""
        if not self._cloud_dns_checked:
            self._cloud_dns_ok = cloud_available()
            self._cloud_dns_checked = True
        return self._cloud_dns_ok

    def _can_use_cloud(self):
        """Check if we should even try cloud (DNS OK, not in failover)."""
        now = time.time()
        if now < self._failover_until:
            return False
        return self._check_cloud_dns()

    def decide_model(self, agent_info, task_type="exec"):
        """
        Decide which model to use for a task.

        Returns (model_name, is_cloud, source) where:
        - model_name: the model to call
        - is_cloud: True if it's a remote cloud model
        - source: "cloud_nvidia" or "local_qwen"
        """
        agent_id = agent_info["agent_id"]
        tier = agent_info["tier"]

        # Determine if agent needs heavy model
        needs_heavy = agent_needs_heavy_model(agent_id)

        # Try cloud first
        cloud_dns = self._check_cloud_dns()
        can_use_cloud = self._can_use_cloud()
        print(f"[decide_model] {agent_id} ({tier}): needs_heavy={needs_heavy}, cloud_dns={cloud_dns}, can_use_cloud={can_use_cloud}", flush=True)

        if can_use_cloud:
            # Determine pool for this tier
            if needs_heavy or tier == "pro":
                pool_name = TIER_POOL_MAP.get("pro", "nvidia_key1")
            else:
                pool_name = TIER_POOL_MAP.get("lite", "nvidia_key3")

            pool = self.router.pools.get(pool_name)
            if pool and self.router.is_available(pool_name):
                models = pool["models"]
                # Pick the heavy model if needed, else first available
                if needs_heavy:
                    model = models[0]  # First model is usually the heavy one (nemotron-3-ultra)
                else:
                    model = self.router._round_robin_model(pool_name)
                print(f"[decide_model] {agent_id}: selected cloud model {model}", flush=True)
                return model, True, "cloud_nvidia"

        # Fall back to local Qwen
        self._record_cloud_failure()
        print(f"[decide_model] {agent_id}: falling back to local Qwen", flush=True)
        return LOCAL_MODEL, False, "local_qwen"

    def _record_cloud_failure(self):
        """Track consecutive cloud failures to trigger failover."""
        self._consecutive_cloud_failures += 1
        if self._consecutive_cloud_failures >= self._cloud_failover_threshold:
            self._failover_until = time.time() + 300  # Skip cloud for 5 minutes
            print(f"[orchestrator] Cloud failover activated for 300s "
                  f"({self._consecutive_cloud_failures} consecutive failures)")

    def _record_cloud_success(self):
        """Reset failure counter on successful cloud call."""
        self._consecutive_cloud_failures = 0
        self._failover_until = 0

    def call_model(self, model, prompt, task_id=None, priority="normal",
                   max_tokens=500, temperature=0.7, timeout=None):
        """
        Call the specified model. Routes to cloud or local based on model name.

        Returns (response_text, model_used, is_cloud) or raises on failure.
        """
        is_cloud = model != LOCAL_MODEL

        if is_cloud:
            return self._call_cloud_model(model, prompt, task_id, priority,
                                          max_tokens, temperature, timeout)
        else:
            return self._call_local_model(prompt, task_id, max_tokens, temperature, timeout)

    def _call_cloud_model(self, model, prompt, task_id, priority, max_tokens,
                          temperature, timeout):
        """Call a cloud NVIDIA model via ProviderClient."""
        # Determine which pool this model belongs to
        pool_name = None
        for name, pool in self.router.pools.items():
            if model in pool["models"]:
                pool_name = name
                break

        if not pool_name:
            raise RuntimeError(f"Model {model} not found in any provider pool")

        client = ProviderClient(pool_name, model)

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
            return response, model, True
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

    def _call_local_model(self, prompt, task_id, max_tokens, temperature, timeout):
        """Call local Qwen3.5-9B via Ollama /v1/completions."""
        full_prompt = f"System: You are a helpful assistant. Answer directly and concisely.\n\nUser: {prompt}\n\nAssistant:"
        payload = json.dumps({
            "model": LOCAL_MODEL + ":latest",
            "prompt": full_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            self.local_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        timeout = timeout or 120
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
            choices = d.get("choices", [])
            if choices:
                text = choices[0].get("text", "N/A")
            else:
                text = "N/A"
            return text, LOCAL_MODEL, False

    def plan_and_execute(self, agent_info, plan_prompt, exec_prompt,
                         task_id=None, priority="normal"):
        """
        Full plan + execute cycle using cloud-or-local model selection.

        Returns (plan_result, exec_result) where each is (text, model, is_cloud).
        """
        # Plan with heavy model (pro agents always use heavy for planning)
        plan_model, plan_is_cloud, plan_source = self.decide_model(
            agent_info, task_type="plan"
        )
        plan_text, plan_model_used, plan_cloud = self.call_model(
            plan_model, plan_prompt, task_id=f"{task_id or 'plan'}-plan",
            priority=priority,
        )

        # Execute with appropriate model
        exec_model, exec_is_cloud, exec_source = self.decide_model(
            agent_info, task_type="exec"
        )
        exec_text, exec_model_used, exec_cloud = self.call_model(
            exec_model, exec_prompt, task_id=f"{task_id or 'exec'}-exec",
            priority=priority,
        )

        return {
            "plan": (plan_text, plan_model_used, plan_cloud),
            "exec": (exec_text, exec_model_used, exec_cloud),
        }

    def status(self):
        """Return orchestrator status for monitoring."""
        cloud_dns = self._check_cloud_dns()
        router_status = self.router.status()
        return {
            "cloud_dns_available": cloud_dns,
            "cloud_failover_active": time.time() < self._failover_until,
            "consecutive_cloud_failures": self._consecutive_cloud_failures,
            "local_model": LOCAL_MODEL,
            "local_url": LOCAL_URL,
            "provider_pools": router_status,
        }


def main():
    """CLI for testing the cloud orchestrator."""
    import argparse

    parser = argparse.ArgumentParser(description="Cloud Model Orchestrator")
    parser.add_argument("action", choices=["status", "test", "plan-exec"])
    parser.add_argument("--agent", default="principal-architect",
                        help="Agent ID for testing")
    parser.add_argument("--tier", default="pro",
                        help="Agent tier (pro/lite)")
    parser.add_argument("--prompt", default="Hello, what is 2+2?",
                        help="Test prompt")
    args = parser.parse_args()

    orch = CloudModelOrchestrator()

    if args.action == "status":
        status = orch.status()
        print(json.dumps(status, indent=2))

    elif args.action == "test":
        agent_info = {"agent_id": args.agent, "tier": args.tier}
        model, is_cloud, source = orch.decide_model(agent_info, task_type="exec")
        print(f"Agent: {args.agent} ({args.tier})")
        print(f"Selected model: {model}")
        print(f"Is cloud: {is_cloud}")
        print(f"Source: {source}")
        print(f"Cloud DNS available: {orch._check_cloud_dns()}")
        if not is_cloud:
            print("Calling local Qwen...")
            text, m, c = orch.call_model(model, args.prompt, task_id="test")
            print(f"Response: {text[:200]}")

    elif args.action == "plan-exec":
        agent_info = {"agent_id": args.agent, "tier": args.tier}
        plan_prompt = f"Plan a task for agent {args.agent}. Respond with TITLE/DESCRIPTION/PRIORITY format."
        exec_prompt = f"Execute: {args.prompt}"
        result = orch.plan_and_execute(agent_info, plan_prompt, exec_prompt,
                                       task_id="test-plan-exec")
        print(f"Plan model: {result['plan'][1]} (cloud={result['plan'][2]})")
        print(f"Plan: {result['plan'][0][:200]}")
        print(f"Exec model: {result['exec'][1]} (cloud={result['exec'][2]})")
        print(f"Exec: {result['exec'][0][:200]}")


if __name__ == "__main__":
    main()