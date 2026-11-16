"""
Router - provider selection with round-robin and rate-limit handling.
Borrowed patterns from openrig (model routing) and open-multi-agent (model routing).
Pool selection persists across CLI invocations via a state file.
"""
import json
import os
import time
import threading
from pathlib import Path


class ProviderRouter:
    def __init__(self, config_path="/Users/aryanagarwal/AI-Office/packages/office-os/config/office.json"):
        with open(config_path) as f:
            self.config = json.load(f)
        self.pools = self.config["provider_pools"]
        self.fallback_chain = self.config.get("fallback_chain", [])
        self.state_path = Path("/Users/aryanagarwal/office-os/config/router_state.json")
        # Per-pool state: cooldown until timestamp, task count for round-robin
        self.cooldowns = {name: 0 for name in self.pools}
        self.task_counts = self._load_task_counts()
        self._lock = threading.Lock()

    def _load_task_counts(self):
        """Load persisted task counts for round-robin across CLI invocations."""
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            return {name: data.get(name, 0) for name in self.pools}
        except (FileNotFoundError, json.JSONDecodeError):
            return {name: 0 for name in self.pools}

    def _save_task_counts(self):
        """Persist task counts to disk."""
        try:
            with open(self.state_path, "w") as f:
                json.dump(self.task_counts, f, indent=2)
        except Exception:
            pass  # Don't crash if we can't write state

    def is_available(self, pool_name):
        """Check if a provider pool is available (not in cooldown)."""
        with self._lock:
            return time.time() > self.cooldowns.get(pool_name, 0)

    def select_provider(self, tier="general", preferred_pool=None):
        """
        Select the best available provider for a given tier.
        Round-robins across available pools of that tier by task count (persisted).
        Falls back through fallback_chain if none available.
        Thread-safe for concurrent worker access.
        """
        def _pool_matches_tier(pool, tier):
            """Check if a pool serves a given tier. Pool tier can be a string or list."""
            ptier = pool["tier"]
            if isinstance(ptier, list):
                return tier in ptier or "any" in ptier
            return ptier in (tier, "any")

        with self._lock:
            # First try preferred pool if specified and available
            if preferred_pool and self.is_available(preferred_pool):
                pool = self.pools[preferred_pool]
                if _pool_matches_tier(pool, tier):
                    self.task_counts[preferred_pool] = self.task_counts.get(preferred_pool, 0) + 1
                    self._save_task_counts()
                    model = self._round_robin_model(preferred_pool)
                    return preferred_pool, model

            # Find all available pools matching the tier
            candidates = []
            for name, pool in self.pools.items():
                if self.is_available(name) and _pool_matches_tier(pool, tier):
                    candidates.append(name)

            if candidates:
                # Round-robin: pick the pool with the fewest tasks assigned
                best = min(candidates, key=lambda n: self.task_counts.get(n, 0))
                self.task_counts[best] = self.task_counts.get(best, 0) + 1
                self._save_task_counts()
                pool = self.pools[best]
                model = self._round_robin_model(best)
                return best, model

            # Fallback chain
            for pool_name in self.fallback_chain:
                if self.is_available(pool_name):
                    pool = self.pools[pool_name]
                    self.task_counts[pool_name] = self.task_counts.get(pool_name, 0) + 1
                    self._save_task_counts()
                    model = self._round_robin_model(pool_name)
                    return pool_name, model

            return None, None

    def mark_rate_limited(self, pool_name, cooldown_sec=None):
        """Mark a pool as rate-limited, set cooldown."""
        cooldown = cooldown_sec or self.pools.get(pool_name, {}).get("cooldown_sec", 60)
        with self._lock:
            self.cooldowns[pool_name] = time.time() + cooldown
        print(f"[router] {pool_name} rate-limited, cooling down for {cooldown}s")

    def mark_daily_quota_exceeded(self, pool_name):
        """Mark a pool as daily-quota-exceeded, cool down until midnight."""
        now = time.time()
        # Calculate seconds until midnight
        import datetime as _dt
        tomorrow = _dt.datetime.now().date() + _dt.timedelta(days=1)
        midnight = _dt.datetime.combine(tomorrow, _dt.datetime.min.time())
        cooldown = midnight.timestamp() - now
        with self._lock:
            self.cooldowns[pool_name] = time.time() + cooldown
        print(f"[router] {pool_name} daily quota exhausted, cooling down for {cooldown/3600:.1f}h until midnight")

    def mark_success(self, pool_name):
        """Record a successful call (no cooldown change, just tracking)."""
        pass

    def _round_robin_model(self, pool_name):
        """Get next model from a pool's model list, round-robin style."""
        pool = self.pools[pool_name]
        models = pool["models"]
        with self._lock:
            if not hasattr(self, "_rr_index"):
                self._rr_index = {}
            idx = self._rr_index.get(pool_name, 0) % len(models)
            self._rr_index[pool_name] = idx + 1
        return models[idx]

    def get_all_pools(self):
        return self.pools

    def status(self):
        """Return status of all pools for monitoring."""
        now = time.time()
        status = {}
        for name, pool in self.pools.items():
            status[name] = {
                "tier": pool["tier"],
                "available": self.is_available(name),
                "cooldown_remaining": max(0, self.cooldowns.get(name, 0) - now),
                "task_count": self.task_counts.get(name, 0),
                "models": pool["models"],
            }
        return status
