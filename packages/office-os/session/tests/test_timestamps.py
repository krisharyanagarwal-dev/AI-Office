"""Requirement 10: milliseconds, future stamps and epoch zero.

The unit is forced by observation, not chosen: real `updatedAt` values are 13
digits and reading one as seconds overflows the representable year range. One
observed value decoded to `2026-10-16T18:39:53Z`, 1.5 minutes before the clock
of the call that returned it.
"""

import pytest

from fixtures_synthetic import FIXTURE_NOW_MS, page, row

from qoder_session_floor import (
    EnvelopeMalformed,
    build_snapshot,
    fold_page,
    new_read_state,
    parse_envelope,
    serialize_snapshot,
    validate_snapshot,
)
import json


def test_observable_epoch_ms_is_thirteen_digits_and_in_range():
    assert len(str(FIXTURE_NOW_MS)) == 13
    assert FIXTURE_NOW_MS // 1000 < 4_000_000_000, "beyond this the value is not seconds"


def test_epoch_zero_is_structurally_valid_and_flagged_not_dropped():
    """A 0 stamp is a real oddity about the source; deleting the row would hide it."""
    envelope = parse_envelope(page([row("fx-zero", updated_at=0)], None), now_ms=FIXTURE_NOW_MS)
    assert envelope.emitted == 1
    assert envelope.suspicious_timestamp_count == 1


def test_future_timestamp_is_flagged_against_the_callers_clock():
    envelope = parse_envelope(
        page([row("fx-future", updated_at=FIXTURE_NOW_MS + 60_000)], None),
        now_ms=FIXTURE_NOW_MS,
    )
    assert envelope.suspicious_timestamp_count == 1


def test_no_suspicion_when_clock_is_not_supplied():
    """`now_ms` is a parameter, so parsing stays pure and deterministic."""
    assert parse_envelope(page([row("fx-future", updated_at=FIXTURE_NOW_MS + 60_000)], None)).suspicious_timestamp_count == 0


@pytest.mark.parametrize("bad", [True, False, "1792200000000", 1.5, None, [1]])
def test_non_integer_timestamp_is_malformed(bad):
    """`isinstance(True, int)` is True in Python; a bool must not pass as a stamp."""
    with pytest.raises(EnvelopeMalformed):
        parse_envelope(page([row("fx-bad", updated_at=bad)], None))


def test_negative_timestamp_is_malformed():
    with pytest.raises(EnvelopeMalformed):
        parse_envelope(page([row("fx-neg", updated_at=-1)], None))


def test_epoch_zero_and_future_stamps_survive_into_validation_problems():
    state = fold_page(
        new_read_state(),
        parse_envelope(
            page([row("fx-zero", updated_at=0), row("fx-future", updated_at=FIXTURE_NOW_MS + 5)], None),
            now_ms=FIXTURE_NOW_MS,
        ),
    )
    snapshot = build_snapshot(state, now_ms=FIXTURE_NOW_MS, producer="synthetic-fixture")
    loaded = json.loads(serialize_snapshot(snapshot))
    problems = validate_snapshot(loaded, now_ms=FIXTURE_NOW_MS)

    assert any("epoch_zero_timestamp" in p for p in problems)
    assert any("timestamp_from_the_future" in p for p in problems)


def test_clock_skew_allowance_is_explicit_and_zero_by_default():
    at_limit = row("fx-edge", updated_at=FIXTURE_NOW_MS)
    state = fold_page(new_read_state(), parse_envelope(page([at_limit], None)))
    loaded = json.loads(serialize_snapshot(build_snapshot(state, now_ms=FIXTURE_NOW_MS, producer="synthetic")))

    assert validate_snapshot(loaded, now_ms=FIXTURE_NOW_MS) == []
    assert any("future" in p for p in validate_snapshot(loaded, now_ms=FIXTURE_NOW_MS - 1))


def test_missing_observed_at_is_rejected_as_a_problem():
    state = fold_page(new_read_state(), parse_envelope(page([row("fx-one")], None)))
    loaded = json.loads(serialize_snapshot(build_snapshot(state, now_ms=FIXTURE_NOW_MS, producer="synthetic")))
    loaded["observedAtMs"] = "yesterday"

    assert "observedAtMs_not_int_ms" in validate_snapshot(loaded, now_ms=FIXTURE_NOW_MS)
