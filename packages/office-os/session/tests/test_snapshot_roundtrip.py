"""Requirement 12 and 13: version refusal, deterministic bytes, invariant checks.

A schema change that parses quietly is the same failure class as an absence
claim from a partial read: the reader believes something the producer never
said. Hence the hard stop on an unknown `schemaVersion`.
"""

import json

import pytest

from fixtures_synthetic import FIXTURE_NOW_MS, four_state_page, page, row

from qoder_session_floor import (
    SCHEMA_VERSION,
    SchemaVersionMismatch,
    build_snapshot,
    fold_page,
    new_read_state,
    parse_envelope,
    parse_snapshot,
    serialize_snapshot,
    validate_snapshot,
)


def _snapshot():
    state = fold_page(new_read_state(checked_at_ms=FIXTURE_NOW_MS), parse_envelope(four_state_page()))
    return build_snapshot(state, now_ms=FIXTURE_NOW_MS, producer="synthetic-fixture")


def test_serialization_is_byte_stable_regardless_of_key_order():
    snapshot = _snapshot()
    shuffled = json.loads(json.dumps(snapshot, sort_keys=False))
    reversed_keys = {k: snapshot[k] for k in reversed(list(snapshot))}

    assert serialize_snapshot(snapshot) == serialize_snapshot(shuffled)
    assert serialize_snapshot(snapshot) == serialize_snapshot(reversed_keys)


def test_roundtrip_is_exact():
    snapshot = _snapshot()
    text = serialize_snapshot(snapshot)
    assert serialize_snapshot(parse_snapshot(text, now_ms=FIXTURE_NOW_MS)) == text


@pytest.mark.parametrize("version", [2, 0, "1", None, "one", [1]])
def test_unsupported_schema_version_refuses_to_parse(version):
    broken = _snapshot()
    broken["schemaVersion"] = version
    with pytest.raises(SchemaVersionMismatch):
        validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)


def test_the_shipped_version_is_the_supported_one():
    assert SCHEMA_VERSION == _snapshot()["schemaVersion"]


def test_evidence_count_must_match_the_sessions_array():
    """A snapshot whose own numbers disagree is not a roster, it is a bug."""
    broken = _snapshot()
    broken["evidence"]["count"] = len(broken["sessions"]) + 3
    assert "count_does_not_match_sessions" in validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)


def test_non_terminal_window_is_flagged_in_the_snapshot():
    broken = _snapshot()
    broken["evidence"]["terminalCursorSeen"] = False
    assert "window_not_terminal" in validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)


def test_duplicate_ids_cannot_be_smuggled_into_a_serialized_snapshot():
    """`fold_page` cannot produce this, so only a hand-edited or merged file can."""
    broken = _snapshot()
    broken["sessions"].append(dict(broken["sessions"][0]))
    problems = validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)
    assert any("duplicate_sessionId" in p for p in problems)


def test_the_forbidden_colliding_key_is_rejected():
    broken = _snapshot()
    broken["sessions"][0]["runtimeState"] = "cold"
    problems = validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)
    assert any("forbidden_runtimeState_key" in p for p in problems)


def test_snapshot_provenance_separates_observed_from_proposed():
    """Field-name honesty is data, not a comment: the file must say which is which."""
    provenance = _snapshot()["provenance"]
    assert set(provenance["observedUpstreamFields"]) == {
        "sessionId",
        "title",
        "cwd",
        "updatedAt",
        "runtimeState",
        "pendingInteractionCount",
        "unread",
        "archived",
    }
    assert "statusLabel" in provenance["proposedFields"]
    assert "qoderRuntimeState" in provenance["proposedFields"]


def test_claims_block_is_computed_from_the_window_not_authored_by_hand():
    snapshot = _snapshot()
    assert snapshot["claims"]["canClaimAbsence"] is False, "four rows were seen"
    assert snapshot["claims"]["canClaimComplete"] is True
    assert snapshot["claims"]["readStatus"] == "has_items"


def test_parse_snapshot_reports_problems_instead_of_returning_a_bad_roster():
    broken = _snapshot()
    broken["sessions"][0].pop("statusLabel")
    with pytest.raises(ValueError) as caught:
        parse_snapshot(serialize_snapshot(broken), now_ms=FIXTURE_NOW_MS)
    assert "statusLabel" in str(caught.value)


def test_invalid_json_is_rejected_as_a_value_error():
    with pytest.raises(ValueError):
        parse_snapshot("{not json", now_ms=FIXTURE_NOW_MS)
