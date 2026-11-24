"""Requirement 1: the contract is proven from serialized JSON, not from an object.

The draft this replaces called `session.compute_status()` from browser
JavaScript on data that had been through `JSON.stringify`, where no methods
survive -- and its tests passed a stubbed-in `{compute_status: () => 'working'}`
object, so they were green whether or not the wire format was ever right. These
tests assert on `json.loads()` output and prove the assertions can fail.
"""

import json

from fixtures_synthetic import FIXTURE_NOW_MS, four_state_page

from qoder_session_floor import (
    build_snapshot,
    fold_page,
    new_read_state,
    parse_envelope,
    parse_snapshot,
    serialize_snapshot,
    validate_snapshot,
)


def _serialized_fixture():
    state = fold_page(new_read_state(), parse_envelope(four_state_page()))
    snapshot = build_snapshot(state, now_ms=FIXTURE_NOW_MS, producer="synthetic-fixture")
    return snapshot, serialize_snapshot(snapshot)


def test_status_label_is_a_serialized_field_not_a_method():
    _, text = _serialized_fixture()
    loaded = json.loads(text)
    by_id = {row["sessionId"]: row for row in loaded["sessions"]}

    assert by_id["fx-running"]["statusLabel"] == "working"
    assert by_id["fx-ready"]["statusLabel"] == "available"
    assert by_id["fx-waiting"]["statusLabel"] == "pending_approval"
    assert by_id["fx-cold"]["statusLabel"] == "off_shift"


def test_upstream_state_is_preserved_and_the_colliding_key_is_gone():
    _, text = _serialized_fixture()
    loaded = json.loads(text)

    assert {row["qoderRuntimeState"] for row in loaded["sessions"]} == {
        "running",
        "ready",
        "waiting-user",
        "cold",
    }
    # The rename exists to stop fleet states coloring Qoder desks; if the old
    # key came back, validation must say so rather than render it.
    assert all("runtimeState" not in row for row in loaded["sessions"])


def test_wire_shape_survives_a_serialize_parse_roundtrip():
    _, text = _serialized_fixture()
    loaded = parse_snapshot(text, now_ms=FIXTURE_NOW_MS)
    assert serialize_snapshot(loaded) == text


def test_removed_status_label_is_caught_on_the_wire():
    """Teeth: strip the field from parsed JSON and validation must notice."""
    snapshot, text = _serialized_fixture()
    broken = json.loads(text)
    broken["sessions"][0].pop("statusLabel")
    problems = validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)
    assert any("statusLabel" in problem for problem in problems)


def test_wrong_status_label_is_caught_on_the_wire():
    """Teeth: a plausible label drawn from the wrong state must not validate."""
    _, text = _serialized_fixture()
    broken = json.loads(text)
    for row in broken["sessions"]:
        if row["qoderRuntimeState"] == "cold":
            row["statusLabel"] = "working"
    problems = validate_snapshot(broken, now_ms=FIXTURE_NOW_MS)
    assert any("statusLabel" in problem for problem in problems)
