"""
The cloud orchestrator must try the local MLX pool before spending on cloud.
"""
import pytest

from core.subs.cloud_orchestrator import CloudModelOrchestrator, TIER_FAILOVER_POOLS

MLX_MODEL = "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4"
LOCAL_POOL = "mlx_local"


@pytest.fixture
def orchestrator():
    orch = CloudModelOrchestrator()
    orch.router.cooldowns = {name: 0 for name in orch.router.pools}
    return orch


@pytest.mark.parametrize("tier", ["pro", "lite", "general"])
def test_every_tier_fails_over_to_mlx_first(tier):
    assert TIER_FAILOVER_POOLS[tier][0] == LOCAL_POOL


@pytest.mark.parametrize("tier", ["pro", "lite", "general"])
def test_decide_model_prefers_the_local_mlx_pool(orchestrator, tier):
    model, pool, is_cloud = orchestrator.decide_model(
        {"agent_id": "general-assistant", "tier": tier}, task_type="exec"
    )
    assert pool == LOCAL_POOL
    assert model == MLX_MODEL


def test_decide_model_falls_back_to_cloud_when_mlx_is_cooling_down(orchestrator):
    orchestrator.router.mark_rate_limited(LOCAL_POOL)
    model, pool, is_cloud = orchestrator.decide_model(
        {"agent_id": "general-assistant", "tier": "general"}, task_type="exec"
    )
    assert pool != LOCAL_POOL
    assert model
