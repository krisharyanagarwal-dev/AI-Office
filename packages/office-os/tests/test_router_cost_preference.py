"""
Zero-cost pool preference in ProviderRouter.

The office must spend nothing on cloud models while the local MLX server is
healthy, but it must still reach the cloud when MLX is down. Selection order is
therefore (cost, task_count): cheapest pool first, round-robin among equals.
"""
from pathlib import Path
import json
import time

import pytest

from core.router import ProviderRouter

MLX_MODEL = "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4"
REAL_CONFIG = str(Path(__file__).resolve().parents[3] / "packages" / "office-os" / "config" / "office.json")


def _router(tmp_path, pools, fallback_chain=None):
    cfg_path = tmp_path / "office.json"
    cfg_path.write_text(json.dumps({
        "provider_pools": pools,
        "fallback_chain": fallback_chain or [],
    }))
    r = ProviderRouter(str(cfg_path))
    r.task_counts = {name: 0 for name in r.pools}
    r._save_task_counts = lambda: None
    return r


@pytest.fixture
def mixed_router(tmp_path):
    # The paid pool is declared first on purpose: without a cost rule the
    # router would pick it (all task counts start at 0).
    return _router(tmp_path, {
        "nvidia_key1": {
            "provider": "nvidia",
            "models": ["nvidia/nemotron-3-ultra-550b-a55b"],
            "tier": "pro",
            "cost": 1,
            "cooldown_sec": 60,
        },
        "mlx_local": {
            "provider": "mlx",
            "models": [MLX_MODEL],
            "tier": ["pro", "general", "lite"],
            "cost": 0,
            "cooldown_sec": 30,
        },
    })


def test_zero_cost_pool_wins_over_costed_pool(mixed_router):
    pool, model = mixed_router.select_provider(tier="pro")
    assert pool == "mlx_local"
    assert model == MLX_MODEL


def test_costed_pool_wins_when_zero_cost_pool_is_cooling_down(mixed_router):
    mixed_router.mark_rate_limited("mlx_local")
    pool, model = mixed_router.select_provider(tier="pro")
    assert pool == "nvidia_key1"


def test_zero_cost_pool_returns_after_cooldown_expires(mixed_router):
    mixed_router.cooldowns["mlx_local"] = time.time() - 1
    pool, _ = mixed_router.select_provider(tier="pro")
    assert pool == "mlx_local"


def test_equal_cost_pools_still_round_robin_by_task_count(tmp_path):
    router = _router(tmp_path, {
        "cheap_a": {"models": ["m-a"], "tier": "pro", "cost": 0},
        "cheap_b": {"models": ["m-b"], "tier": "pro", "cost": 0},
    })
    first, _ = router.select_provider(tier="pro")
    second, _ = router.select_provider(tier="pro")
    assert first != second, "equal-cost pools must keep round-robin by task count"


def test_preferred_pool_overrides_cost_preference(mixed_router):
    pool, _ = mixed_router.select_provider(tier="pro", preferred_pool="nvidia_key1")
    assert pool == "nvidia_key1"


def test_status_reports_pool_cost(mixed_router):
    assert mixed_router.status()["mlx_local"]["cost"] == 0
    assert mixed_router.status()["nvidia_key1"]["cost"] == 1


def test_real_config_defines_zero_cost_mlx_pool():
    with open(REAL_CONFIG) as f:
        cfg = json.load(f)
    pools = cfg["provider_pools"]
    assert "mlx_local" in pools, "config/office.json must define the local MLX pool"
    mlx = pools["mlx_local"]
    assert mlx["cost"] == 0, "the local MLX pool must be marked zero-cost"
    assert MLX_MODEL in mlx["models"]
    assert set(mlx["tier"]) >= {"pro", "general", "lite"}
    assert cfg["fallback_chain"][0] == "mlx_local", "MLX must lead the fallback chain"
