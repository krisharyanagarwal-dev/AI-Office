"""Regression tests for FaithDirector.adjust_topic_mix.

engagement_rate is stored at the top level of each performance record, not
inside its metrics dict, so adjust_topic_mix must read it from there. The
office-os checkout location comes from OFFICE_OS_DIR, which these tests point
at a temp directory.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

AGENT_PATH = Path(__file__).resolve().parents[1] / "agents" / "faith_director.py"


@pytest.fixture
def director_mod(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFICE_OS_DIR", str(tmp_path))
    # faith_director imports core.hive / core.router from the external checkout;
    # stub them so the module loads anywhere.
    hive_mod = types.ModuleType("core.hive")
    setattr(hive_mod, "Hive", object)
    router_mod = types.ModuleType("core.router")
    setattr(router_mod, "ProviderRouter", object)
    monkeypatch.setitem(sys.modules, "core", types.ModuleType("core"))
    monkeypatch.setitem(sys.modules, "core.hive", hive_mod)
    monkeypatch.setitem(sys.modules, "core.router", router_mod)
    spec = importlib.util.spec_from_file_location("faith_director_under_test", AGENT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _director(mod):
    d = mod.FaithDirector.__new__(mod.FaithDirector)
    d.hive = types.SimpleNamespace(_now=lambda: "now")
    return d


def test_adjust_topic_mix_fires_when_english_outperforms(director_mod, monkeypatch):
    d = _director(director_mod)
    shifts = []
    monkeypatch.setattr(d, "_apply_queue_shift", lambda pct, favor: shifts.append((pct, favor)))

    for i in range(3):
        d.record_performance(f"en{i}", {"language": "english", "views": 100, "likes": 40, "comments": 10, "shares": 0})
        d.record_performance(f"hi{i}", {"language": "hindi", "views": 100, "likes": 5, "comments": 0, "shares": 0})

    d.adjust_topic_mix()

    assert len(shifts) == 1
    pct, favor_english = shifts[0]
    assert favor_english is True
    assert 0 < pct <= 0.1


def test_adjust_topic_mix_no_shift_without_enough_samples(director_mod, monkeypatch):
    d = _director(director_mod)
    shifts = []
    monkeypatch.setattr(d, "_apply_queue_shift", lambda pct, _favor: shifts.append(pct))
    d.record_performance("en0", {"language": "english", "views": 100, "likes": 90})
    d.adjust_topic_mix()
    assert shifts == []
