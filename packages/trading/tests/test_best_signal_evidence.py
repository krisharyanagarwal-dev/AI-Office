"""Tests for the evidence registry behind the best-signal bot.

The registry is the bot's memory: it records which signal survived the
archived out-of-sample work, which did not, and which artifacts justify each
verdict. A citation that does not resolve on disk is a failed gate, not a
footnote.
"""
import pytest

from best_signal.evidence import (
    REPO_ROOT,
    CandidateRecord,
    Citation,
    candidate_gates,
    default_registry,
    rank_candidates,
    ranking_table,
    select_tradable,
    verify_citations,
)


def _record(name):
    for record in default_registry():
        if record.name == name:
            return record
    raise AssertionError(f"no registry entry named {name}")


class TestRegistry:
    def test_repo_root_contains_the_packages_directory(self):
        assert (REPO_ROOT / "packages").is_dir()

    def test_structural_carry_is_the_only_accepted_candidate(self):
        accepted = [r.name for r in default_registry() if r.status == "ACCEPTED"]
        assert accepted == ["always_on_carry"]

    def test_accepted_candidate_records_the_archived_oos_numbers(self):
        record = _record("always_on_carry")
        assert record.kind == "structural"
        assert record.metrics["btc_oos_net"] == pytest.approx(350.30)
        assert record.metrics["eth_oos_net"] == pytest.approx(253.54)
        assert record.metrics["flips"] == 0

    def test_timing_flip_candidate_is_rejected(self):
        record = _record("persistence_flip_carry")
        assert record.status == "REJECTED"
        assert record.kind == "timing"

    def test_flip_rejection_cites_the_archived_verdict(self):
        joined = " ".join(_record("persistence_flip_carry").reasons).lower()
        assert "no skill" in joined
        assert "constant-side" in joined

    def test_flip_rejection_records_the_churn_baseline(self):
        metrics = _record("persistence_flip_carry").metrics
        assert metrics["btc_churn_oos_net"] == pytest.approx(-897.80)
        assert metrics["eth_churn_oos_net"] == pytest.approx(-1015.44)

    def test_mean_reversion_candidate_is_rejected(self):
        record = _record("edge_probe_1h4h")
        assert record.status == "REJECTED"
        assert "no validated edge" in " ".join(record.reasons).lower()

    def test_ml_lowturn_candidate_is_not_accepted(self):
        record = _record("ml_lowturn_ridge_20d")
        assert record.status != "ACCEPTED"
        assert "sigma" in " ".join(record.reasons).lower()

    def test_candidate_names_are_unique(self):
        names = [r.name for r in default_registry()]
        assert len(names) == len(set(names))

    def test_every_candidate_has_at_least_one_citation(self):
        for record in default_registry():
            assert record.citations


class TestGates:
    def test_every_cited_artifact_exists_on_disk(self):
        assert verify_citations(default_registry()) == []

    def test_missing_citation_fails_the_gate(self):
        record = CandidateRecord(
            name="ghost",
            thesis="t",
            kind="timing",
            status="ACCEPTED",
            reasons=(),
            citations=(Citation("packages/_archive/does_not_exist.json", "nope"),),
        )
        gates = candidate_gates(record)
        assert gates["citations_present"] is False
        assert gates["tradable"] is False

    def test_accepted_candidate_with_present_citations_is_tradable(self):
        gates = candidate_gates(_record("always_on_carry"))
        assert gates["tradable"] is True

    def test_rejected_candidate_is_never_tradable(self):
        assert candidate_gates(_record("edge_probe_1h4h"))["tradable"] is False


class TestRanking:
    def test_accepted_candidate_ranks_first(self):
        ranked = rank_candidates(default_registry())
        assert ranked[0].name == "always_on_carry"

    def test_ranking_is_deterministic(self):
        first = [r.name for r in rank_candidates(default_registry())]
        second = [r.name for r in rank_candidates(default_registry())]
        assert first == second

    def test_table_rows_carry_rank_status_and_citations(self):
        rows = ranking_table(default_registry())
        assert rows[0]["rank"] == 1
        assert rows[0]["name"] == "always_on_carry"
        assert rows[0]["status"] == "ACCEPTED"
        assert rows[0]["citations"]

    def test_select_tradable_returns_the_accepted_candidate(self):
        chosen = select_tradable(default_registry())
        assert chosen is not None
        assert chosen.name == "always_on_carry"

    def test_select_tradable_returns_none_when_nothing_is_accepted(self):
        records = [
            CandidateRecord(
                name="x",
                thesis="t",
                kind="timing",
                status="RESEARCH",
                reasons=(),
                citations=(),
            )
        ]
        assert select_tradable(records) is None

    def test_select_tradable_refuses_when_two_candidates_are_accepted(self):
        base = _record("always_on_carry")
        twin = CandidateRecord(
            name="second",
            thesis="t",
            kind="structural",
            status="ACCEPTED",
            reasons=(),
            citations=base.citations,
        )
        assert select_tradable([base, twin]) is None
