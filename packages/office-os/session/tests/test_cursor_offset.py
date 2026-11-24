"""Requirement 2 and 4: item-offset arithmetic, and a cursor that refuses to advance.

Observed arithmetic, reproduced as fixtures: `limit=1 -> nextCursor "1"`,
`limit=2 -> nextCursor "2"`, `limit=50` over 42 sessions `-> null`. The rejected
alternative is the integer page counter from the superseded plan, which with
`limit=50` sends `"2"` where `"50"` is required.
"""

import pytest

from fixtures_synthetic import (
    FIXTURE_NOW_MS,
    one_row_page,
    page,
    row,
    terminal_page,
    two_row_page,
)

from qoder_session_floor import (
    EnvelopeMalformed,
    can_claim_complete,
    fold_page,
    new_read_state,
    parse_envelope,
    parse_cursor,
    to_window,
)


def test_cursor_parses_as_an_offset_not_a_page_index():
    assert parse_cursor("1") == 1
    assert parse_cursor("2") == 2
    assert parse_cursor(None) is None


@pytest.mark.parametrize("bad", ["", "-1", "01", "1.5", "2 ", "abc", 1, True, 0])
def test_non_offset_cursor_formats_are_rejected(bad):
    with pytest.raises(EnvelopeMalformed):
        parse_cursor(bad)


def test_single_row_page_advertises_offset_one():
    state = fold_page(new_read_state(), parse_envelope(one_row_page()))
    assert state.cursor_offsets == (0,)
    assert state.expected_next_cursor == 1
    assert state.inconsistencies == ()


def test_two_row_page_advertises_offset_two():
    state = fold_page(new_read_state(), parse_envelope(two_row_page()))
    assert state.items_declared == 2
    assert state.expected_next_cursor == 2
    assert state.inconsistencies == ()


def test_terminal_page_has_no_cursor_and_finishes_the_walk():
    state = fold_page(new_read_state(), parse_envelope(terminal_page()))
    assert state.terminal_cursor_seen is True
    assert state.cut_off is False
    assert can_claim_complete(to_window(state)) is True


def test_page_counter_arithmetic_is_detected_as_a_jump():
    """The superseded plan's bug, asserted as caught rather than merely avoided.

    A second page asked for at offset 1 instead of 2 re-reads a row: dedup hides
    the double count, so the cursor arithmetic has to be what fails.
    """
    first = fold_page(new_read_state(), parse_envelope(two_row_page()))
    overlapping = page([row("fx-bravo"), row("fx-charlie")], "3")
    drifted = fold_page(first, parse_envelope(overlapping), requested_cursor=1)

    assert any("cursor_jump" in item for item in drifted.inconsistencies)
    assert drifted.duplicates_seen == 1
    assert can_claim_complete(to_window(drifted)) is False


def test_repeated_cursor_offset_is_rejected_as_non_advancing():
    first = fold_page(new_read_state(), parse_envelope(one_row_page()))
    again = fold_page(first, parse_envelope(one_row_page()), requested_cursor=0)

    assert any("non_advancing_cursor:0" in item for item in again.inconsistencies)


def test_cursor_that_disagrees_with_page_length_is_flagged():
    """Offset arithmetic must match rows delivered, or the roster moved mid-read."""
    lying = page([row("fx-alpha")], "9")
    state = fold_page(new_read_state(), parse_envelope(lying))
    assert any("offset_mismatch" in item for item in state.inconsistencies)


def test_max_page_guard_marks_the_read_truncated():
    """A page ceiling is a guard, so hitting it must downgrade the claim."""
    more = page([row(f"fx-id-{index}") for index in range(2, 4)], "4")
    state = new_read_state(max_pages=2, checked_at_ms=FIXTURE_NOW_MS)
    state = fold_page(state, parse_envelope(two_row_page()))
    state = fold_page(state, parse_envelope(more), requested_cursor=2)

    window = to_window(state)
    assert state.pages_fetched == 2
    assert state.terminal_cursor_seen is False
    assert state.cut_off is True
    assert window["truncated"] is True
    assert window["pagesFetched"] == 2
    assert state.inconsistencies == ()
    assert can_claim_complete(window) is False
