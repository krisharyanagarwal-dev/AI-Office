"""
Tests for the mini's job runner.

The runner is written for the mini's Python 3.9 and runs there, but its validation
is pure stdlib and imports fine here, which is the point: the contract that keeps a
9B model honest is testable without a model.

The gate that matters is require_evidence. It checks the EVIDENCE, not the answer,
so a verdict can only be claimed when the facts actually support it. Everything else
in the ladder can be fooled by a confident answer; this cannot.
"""
import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[1] / "runner" / "job_runner.py"
_spec = importlib.util.spec_from_file_location("job_runner", _path)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

SCHEMA = {
    "boundary_verdict": ["PASS", "BREACH", "NOT_VERIFIED"],
    "open_positions": "integer|null",
    "realized_pnl": "number|null",
    "cites": "string",
}
RULES = [{
    "when": {"boundary_verdict": "PASS"},
    "require_evidence": ["mode==paper", "execution_enabled==False", "live_trading==False"],
    "why": "PASS may only be claimed when the evidence shows all three",
}]
PAPER = {"mode": "paper", "execution_enabled": False, "live_trading": False}
GOOD = {"boundary_verdict": "PASS", "open_positions": 0, "realized_pnl": 0.0, "cites": "mode"}


# ---------- schema ----------
def test_a_correct_answer_passes():
    assert runner.validate_schema(GOOD, SCHEMA) == []


def test_the_real_failure_from_the_first_run():
    """Run 1 returned the positions ARRAY as open_positions and cites as a LIST."""
    bad = dict(GOOD, open_positions=[], cites=["mode", "live_trading"])
    problems = runner.validate_schema(bad, SCHEMA)
    assert any("open_positions" in p for p in problems)
    assert any("cites" in p for p in problems)


def test_invented_fields_are_rejected():
    assert any("invented field" in p
               for p in runner.validate_schema(dict(GOOD, confidence=0.9), SCHEMA))


def test_value_outside_the_enum_is_rejected():
    assert runner.validate_schema(dict(GOOD, boundary_verdict="PROBABLY_FINE"), SCHEMA)


def test_booleans_are_not_integers():
    """json.loads gives True for `true`; an integer count must not accept it."""
    assert runner.validate_schema(dict(GOOD, open_positions=True), SCHEMA)


def test_null_only_where_declared():
    assert runner.validate_schema(dict(GOOD, open_positions=None), SCHEMA) == []
    assert runner.validate_schema(dict(GOOD, cites=None), SCHEMA)


# ---------- the anti-hallucination gate ----------
def test_pass_is_accepted_when_the_evidence_supports_it():
    assert runner.check_acceptance(GOOD, PAPER, RULES) == []


@pytest.mark.parametrize("evidence,missing", [
    ({"mode": "live", "execution_enabled": False, "live_trading": False}, "mode"),
    ({"mode": "paper", "execution_enabled": True, "live_trading": False}, "execution_enabled"),
    ({"mode": "paper", "execution_enabled": False, "live_trading": True}, "live_trading"),
])
def test_a_claimed_pass_is_rejected_when_the_evidence_contradicts_it(evidence, missing):
    """The model says the boundary is fine; the facts say otherwise. Facts win."""
    problems = runner.check_acceptance(GOOD, evidence, RULES)
    assert problems and missing in problems[0]


def test_a_claimed_pass_is_rejected_when_the_evidence_is_absent():
    """Silence is not consent: a missing fact cannot support a PASS."""
    problems = runner.check_acceptance(GOOD, {"mode": "paper"}, RULES)
    assert problems and "evidence has no execution_enabled" in problems[0]


# ---------- derived facts: computed in code, never asked of the model ----------
def test_age_is_derived_from_an_iso_stamp_with_a_trailing_z():
    """The killswitch file stamps 2026-11-22T22:20:17.999192Z; 3.9's
    fromisoformat rejects the Z, which is why the parse is explicit."""
    import time, calendar
    recent = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(time.time() - 600))
    age = runner.iso_age_min(recent)
    assert age is not None and 9 < age < 11


def test_unparseable_or_missing_stamp_derives_to_none():
    assert runner.iso_age_min("not a date") is None
    assert runner.iso_age_min(None) is None


def test_counts_are_derived_from_the_evidence():
    facts = {"findings": [{"ok": True}, {"ok": False}, {"ok": True}], "surfaces": []}
    out = runner.derive_facts(facts, {
        "findings_total": {"count_of": "findings"},
        "findings_failed": {"count_where_false": ["findings", "ok"]},
        "no_other_surfaces": {"is_empty": "surfaces"},
    })
    assert out["findings_total"] == 3
    assert out["findings_failed"] == 1
    assert out["no_other_surfaces"] is True


def test_a_broken_derive_rule_yields_none_not_a_crash():
    out = runner.derive_facts({"x": 1}, {"bad": {"count_of": "missing"}})
    assert out["bad"] is None


# ---------- numeric clauses ----------
@pytest.mark.parametrize("clause,evidence,ok", [
    ("status_age_min<=60", {"status_age_min": 3.4}, True),
    ("status_age_min<=60", {"status_age_min": 240.0}, False),
    ("drift_count==0", {"drift_count": 0}, True),
    ("findings_failed<1", {"findings_failed": 0}, True),
    ("findings_failed<1", {"findings_failed": 2}, False),
])
def test_numeric_clauses(clause, evidence, ok):
    assert runner.check_clause(clause, evidence)[0] is ok


def test_a_numeric_clause_on_an_absent_field_fails():
    """A freshness claim cannot rest on an age the evidence never supplied."""
    ok, detail = runner.check_clause("status_age_min<=60", {})
    assert not ok and "no status_age_min" in detail


def test_a_numeric_clause_on_a_non_numeric_value_fails():
    ok, detail = runner.check_clause("status_age_min<=60", {"status_age_min": "soon"})
    assert not ok and "not numeric" in detail


def test_rules_do_not_fire_on_other_verdicts():
    other = dict(GOOD, boundary_verdict="NOT_VERIFIED")
    assert runner.check_acceptance(other, {"mode": "live"}, RULES) == []


def test_require_output_not_null():
    rules = [{"when": {"boundary_verdict": "PASS"},
              "require_output_not_null": ["open_positions"], "why": "unfalsifiable"}]
    assert runner.check_acceptance(dict(GOOD, open_positions=None), PAPER, rules)
    assert runner.check_acceptance(GOOD, PAPER, rules) == []


# ---------- the third gate: the model's numbers must match the facts ----------
MATCH_RULES = [{
    "when": {"scope_verdict": "PARTIAL"},
    "require_output_matches_evidence": {"other_surfaces_count": "other_surfaces_total"},
    "why": "a count in a typed field can be checked; prose cannot",
}]


def test_a_matching_count_passes():
    answer = {"scope_verdict": "PARTIAL", "other_surfaces_count": 0}
    assert runner.check_acceptance(answer, {"other_surfaces_total": 0}, MATCH_RULES) == []


def test_a_misstated_count_is_rejected():
    """killswitch-audit run 1 asserted in prose that other_live_surfaces was
    'non-empty' when it was []. As a typed field that claim is catchable."""
    answer = {"scope_verdict": "PARTIAL", "other_surfaces_count": 2}
    problems = runner.check_acceptance(answer, {"other_surfaces_total": 0}, MATCH_RULES)
    assert problems and "but the evidence says" in problems[0]


def test_a_count_with_no_evidence_to_check_against_is_rejected():
    answer = {"scope_verdict": "PARTIAL", "other_surfaces_count": 0}
    problems = runner.check_acceptance(answer, {}, MATCH_RULES)
    assert problems and "cannot check" in problems[0]


def test_numeric_equality_survives_type_differences():
    """json may give 0 or 0.0; the gate is about the value, not the type."""
    answer = {"scope_verdict": "PARTIAL", "other_surfaces_count": 0}
    assert runner.check_acceptance(answer, {"other_surfaces_total": 0.0}, MATCH_RULES) == []


def test_prose_is_not_gated_and_that_is_the_point():
    """A reason field can say anything; nothing here can catch it. This test exists
    to record the limit, so facts are kept in typed fields instead."""
    answer = {"scope_verdict": "PARTIAL", "other_surfaces_count": 0,
              "reason": "other_live_surfaces is non-empty"}   # false, and unverifiable
    assert runner.check_acceptance(answer, {"other_surfaces_total": 0}, MATCH_RULES) == []
