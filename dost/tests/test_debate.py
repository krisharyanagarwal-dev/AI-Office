"""Fleet debate determinism tests (Interpretation E).

dispatch_debate_to_fleet fans one question to multiple agents and must be
deterministic given the same inputs: same agent set, same answers, same
synthesis, one task file per agent sharing one debate_id. All external
dependencies (orchestrator, cache, hive, pnl, memory) are stubbed.
"""

from __future__ import annotations

from dost import dost_main


TIERS = {
    "strategy-advisor": "pro",
    "cost-analyst": "pro",
    "risk-manager": "pro",
    "research-analyst": "pro",
}


def _stub_debate_deps(monkeypatch, tmp_path, call_log):
    monkeypatch.setattr(dost_main, "HIVE_DIR", tmp_path / "hive")
    monkeypatch.setattr(dost_main, "_agent_tiers", lambda: dict(TIERS))
    monkeypatch.setattr(dost_main, "build_context", lambda: "CTX")
    monkeypatch.setattr(dost_main, "_check_pool_cooldowns", lambda: {})
    monkeypatch.setattr(dost_main, "_record_debate_to_pnl", lambda *a, **k: None)
    monkeypatch.setattr(dost_main, "_cache_answer", lambda *a, **k: None)
    monkeypatch.setattr(dost_main.MEMORY, "add_interaction", lambda *a, **k: None)

    def fake_call(orchestrator, agent_info, full_prompt, task_id, pool_cooldowns,
                  max_retries, debug):
        agent = agent_info["agent_id"]
        call_log.append(agent)
        assert "CTX" in full_prompt and "QUESTION:" in full_prompt
        if agent == "risk-manager":
            return None, None, None, "provider timeout"
        return f"answer from {agent}", "qwen-model", "free_local", None

    monkeypatch.setattr(dost_main, "_call_with_retry", fake_call)
    monkeypatch.setattr(
        dost_main,
        "_synthesize_debate",
        lambda prompt, answers: f"{len(answers)} agents answered",
    )


def test_debate_dry_run_writes_nothing_and_calls_nobody(tmp_path, monkeypatch):
    call_log = []
    _stub_debate_deps(monkeypatch, tmp_path, call_log)

    result = dost_main.dispatch_debate_to_fleet(
        "should we add the NSE edge strategy?", dry_run=True
    )

    assert result["dry_run"] is True
    assert result["task_ids"] == []
    assert result["answers"] == []
    assert result["synthesis"] is None
    assert result["cost_units"] == 0
    assert result["debate_id"].startswith("debate-")
    assert set(result["agents"]) == {"strategy-advisor", "cost-analyst", "risk-manager"}
    assert "should we add the NSE edge strategy" in result["message"]
    assert not call_log
    assert not (tmp_path / "hive").exists() or not any((tmp_path / "hive").glob("*.json"))


def test_debate_filters_dedupes_and_falls_back_to_defaults(monkeypatch, tmp_path):
    call_log = []
    _stub_debate_deps(monkeypatch, tmp_path, call_log)

    # unknown agent dropped, duplicates removed, order preserved
    result = dost_main.dispatch_debate_to_fleet(
        "Q",
        agents=["risk-manager", "strategy-advisor", "risk-manager", "bogus-agent"],
    )
    assert call_log == ["risk-manager", "strategy-advisor"]
    assert result["agents"] == ["risk-manager", "strategy-advisor"]

    call_log.clear()
    # no known agents -> fall back to DEBATE_DEFAULT_AGENTS
    monkeypatch.setattr(dost_main, "_agent_tiers", lambda: {"only-x": "pro"})
    result = dost_main.dispatch_debate_to_fleet("Q", agents=["bogus-agent"])
    assert set(call_log) == set(dost_main.DEBATE_DEFAULT_AGENTS)
    assert result["agents"] == list(dost_main.DEBATE_DEFAULT_AGENTS)


def test_debate_writes_one_task_file_per_agent_with_shared_debate_id(tmp_path, monkeypatch):
    call_log = []
    _stub_debate_deps(monkeypatch, tmp_path, call_log)

    result = dost_main.dispatch_debate_to_fleet("Q", agents=["strategy-advisor", "cost-analyst"])

    assert result["debate_id"].startswith("debate-")
    assert len(result["task_ids"]) == 2
    hive = tmp_path / "hive"
    written = sorted(p.name for p in hive.glob("*.json"))
    assert len(written) == 2
    for task_id in result["task_ids"]:
        task = dost_main.json.loads((hive / f"{task_id}.json").read_text())
        assert task["metadata"]["debate"] is True
        assert task["metadata"]["debate_id"] == result["debate_id"]
        assert task["metadata"]["source"] == "dost"
        assert task["title"] == "Debate: Q"
        assert task["agent_id"] in ("strategy-advisor", "cost-analyst")
        assert task["status"] == "done"
        assert task["result"]["text"].startswith("answer from")


def test_debate_error_agent_recorded_but_synthesis_still_returned(tmp_path, monkeypatch):
    call_log = []
    _stub_debate_deps(monkeypatch, tmp_path, call_log)

    result = dost_main.dispatch_debate_to_fleet("Q", agents=["risk-manager", "strategy-advisor"])

    assert call_log == ["risk-manager", "strategy-advisor"]
    by_agent = {a["agent_id"]: a for a in result["answers"]}
    assert by_agent["risk-manager"]["error"] == "provider timeout"
    assert by_agent["risk-manager"]["answer"] is None
    assert by_agent["strategy-advisor"]["answer"] == "answer from strategy-advisor"
    assert result["synthesis"] == "2 agents answered"


def test_debate_cache_hit_skips_provider_and_cache_writes(tmp_path, monkeypatch):
    call_log = []
    _stub_debate_deps(monkeypatch, tmp_path, call_log)
    cached = {
        "debate_id": "debate-cached1",
        "agents": [{"agent_id": "a", "tier": "pro"}],
        "agent_answers": [{"agent_id": "a", "tier": "pro", "answer": "cached answer"}],
        "answer": "cached synthesis",
        "synthesis": "cached synthesis",
        "cost_units": 3,
    }
    monkeypatch.setattr(dost_main, "_get_cached_answer", lambda h: cached)

    result = dost_main.dispatch_debate_to_fleet("repeat question")

    assert result["_cached"] is True
    assert result["debate_id"] == "debate-cached1"
    assert result["synthesis"] == "cached synthesis"
    assert result["answers"][0]["answer"] == "cached answer"
    assert not call_log  # no provider calls on a cache hit


def test_debate_deterministic_same_answers_across_runs(tmp_path, monkeypatch):
    """Same prompt + same agent answers => identical answers and synthesis."""
    results = []
    for _ in range(2):
        call_log = []
        _stub_debate_deps(monkeypatch, tmp_path, call_log)
        results.append(dost_main.dispatch_debate_to_fleet("determinism check"))

    assert results[0]["debate_id"] != results[1]["debate_id"]  # fresh UUID each run
    assert [a["answer"] for a in results[0]["answers"]] == [a["answer"] for a in results[1]["answers"]]
    assert results[0]["synthesis"] == results[1]["synthesis"]
    assert results[0]["agents"] == results[1]["agents"]


# ---------------------------------------------------------------- synthesis

def test_synthesize_debate_fallback_all_errored(monkeypatch):
    monkeypatch.setattr(dost_main, "chat_completion", lambda *a, **k: {"text": ""})

    text = dost_main._synthesize_debate(
        "Q",
        [
            {"agent_id": "a", "tier": "pro", "error": "down"},
            {"agent_id": "b", "tier": "pro", "error": "down"},
        ],
    )
    assert text == "0 of 2 agents returned an answer (all errored)."


def test_synthesize_debate_fallback_partial_answers(monkeypatch):
    monkeypatch.setattr(dost_main, "chat_completion", lambda *a, **k: {"text": ""})

    text = dost_main._synthesize_debate(
        "Q",
        [
            {"agent_id": "a", "tier": "pro", "error": "down"},
            {"agent_id": "b", "tier": "pro", "answer": "yes, do it"},
            {"agent_id": "c", "tier": "pro", "answer": "yes, do it"},
        ],
    )
    assert "2 of 3 agents answered" in text
    assert "Responding agents: b, c" in text
    assert "No clear agreement/disagreement breakdown" in text
