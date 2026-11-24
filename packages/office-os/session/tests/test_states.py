"""Requirements 5 and 6: unknown states are preserved, observed states are covered.

`cold` is the forbidden fallback. The superseded spec said "Invalid
`runtimeState` -> default to `cold`", which renders an unrecognised state as a
worker who has gone home.
"""

import pytest

from fixtures_synthetic import FIXTURE_NOW_MS, four_state_page, page, row

from qoder_session_floor import (
    OBSERVED_RUNTIME_STATES,
    UNKNOWN_LABEL,
    build_snapshot,
    fold_page,
    is_observed_state,
    new_read_state,
    parse_envelope,
    serialize_snapshot,
    status_label,
    validate_snapshot,
)
from qoder_session_floor.states import PROVISIONAL_STATUS_LABELS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("running", "working"),
        ("ready", "available"),
        ("waiting-user", "pending_approval"),
        ("cold", "off_shift"),
    ],
)
def test_every_observed_state_has_a_proposed_label(raw, expected):
    assert status_label(raw) == expected


def test_observed_state_vocabulary_is_covered_exactly():
    assert frozenset(PROVISIONAL_STATUS_LABELS) == OBSERVED_RUNTIME_STATES


@pytest.mark.parametrize("raw", ["teleporting", "", "   ", "Running", "COLD", None, 5, True, ["cold"]])
def test_unrecognised_states_never_become_cold(raw):
    assert status_label(raw) == UNKNOWN_LABEL
    assert status_label(raw) != "off_shift"


def test_state_is_preserved_verbatim_even_when_unmappable():
    state = fold_page(
        new_read_state(),
        parse_envelope(page([row("fx-weird", "teleporting")], None)),
    )
    snapshot = build_snapshot(state, now_ms=FIXTURE_NOW_MS, producer="synthetic-fixture")
    loaded = __import__("json").loads(serialize_snapshot(snapshot))

    assert loaded["sessions"][0]["qoderRuntimeState"] == "teleporting"
    assert loaded["sessions"][0]["statusLabel"] == UNKNOWN_LABEL
    assert validate_snapshot(loaded, now_ms=FIXTURE_NOW_MS) == []


def test_is_observed_state_distinguishes_known_from_invented():
    assert is_observed_state("waiting-user") is True
    assert is_observed_state("waiting_user") is False, "the underscore variant was never observed"
