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
    assert problems and "absent" in problems[0]


def test_rules_do_not_fire_on_other_verdicts():
    other = dict(GOOD, boundary_verdict="NOT_VERIFIED")
    assert runner.check_acceptance(other, {"mode": "live"}, RULES) == []


def test_require_output_not_null():
    rules = [{"when": {"boundary_verdict": "PASS"},
              "require_output_not_null": ["open_positions"], "why": "unfalsifiable"}]
    assert runner.check_acceptance(dict(GOOD, open_positions=None), PAPER, rules)
    assert runner.check_acceptance(GOOD, PAPER, rules) == []
