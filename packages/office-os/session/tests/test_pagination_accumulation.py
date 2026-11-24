"""Requirement 3, 5, 6 and 11: accumulation, roster drift, deterministic conflicts.

The mutation that motivated this file is real and was observed, not invented:
between two `list_chat_sessions` calls, a session entered the top of the list
and this session's own `updatedAt` advanced, changing the order the pages are
returned in. A producer that reads its own roster is a producer standing on the
thing it is measuring.
"""

from fixtures_synthetic import FIXTURE_NOW_MS, empty_terminal_page, page, row, terminal_page, two_row_page

from qoder_session_floor import (
    can_claim_absence,
    can_claim_complete,
    fold_page,
    new_read_state,
    parse_envelope,
    read_status,
    to_window,
)


def test_clean_walk_accumulates_without_duplicating():
    state = new_read_state(checked_at_ms=FIXTURE_NOW_MS)
    state = fold_page(state, parse_envelope(two_row_page()))
    state = fold_page(state, parse_envelope(page([row("fx-2"), row("fx-3")], "4")), requested_cursor=2)
    state = fold_page(state, parse_envelope(terminal_page(start_at=4, count=2)), requested_cursor=4)

    window = to_window(state)
    assert state.items_declared == 6
    assert window["count"] == 6
    assert window["scanned"] == 6
    assert state.duplicates_seen == 0
    assert state.inconsistencies == ()
    assert can_claim_complete(window) is True


def test_roster_changing_mid_read_is_deduplicated_but_not_declared_complete():
    """Deduplication alone must not establish completeness."""
    first = fold_page(new_read_state(), parse_envelope(two_row_page()))
    # A new session was inserted at the head, pushing fx-bravo onto the next page.
    shifted = page([row("fx-bravo"), row("fx-charlie"), row("fx-delta")], "5")
    state = fold_page(first, parse_envelope(shifted), requested_cursor=2)

    window = to_window(state)
    assert state.duplicates_seen == 1
    assert window["count"] == 4, "the duplicate is tidied"
    assert window["scanned"] == 5, "and what was read stays visible"
    assert can_claim_complete(window) is False, "tidying is not proof of a full roster"
    assert read_status(window) == "has_items", "four rows really were seen"


def test_newest_observation_of_an_id_wins_whatever_the_page_order():
    stale = row("fx-same", "cold", updated_at=1_792_100_000_000)
    fresh = row("fx-same", "running", updated_at=1_792_200_000_000)

    forward = fold_page(
        fold_page(new_read_state(), parse_envelope(page([stale], "1"))),
        parse_envelope(page([fresh], "1")),
        requested_cursor=0,
    )
    backward = fold_page(
        fold_page(new_read_state(), parse_envelope(page([fresh], "1"))),
        parse_envelope(page([stale], "1")),
        requested_cursor=0,
    )

    assert forward.items == backward.items == {"fx-same": fresh}
    assert forward.duplicates_seen == backward.duplicates_seen == 1


def test_identical_duplicate_is_counted_and_not_treated_as_a_conflict():
    again = page([row("fx-same")], "1")
    state = fold_page(fold_page(new_read_state(), parse_envelope(again)), parse_envelope(again), requested_cursor=0)

    assert state.duplicates_seen == 1
    assert state.identical_duplicates == 1
    assert state.ties_resolved_first_seen == 0
    assert not any("unresolvable_tie" in item for item in state.inconsistencies)


def test_same_timestamp_different_content_is_an_unresolved_tie():
    """Content differs at one stamp: nothing here can pick a winner."""
    a = row("fx-same", "cold")
    b = dict(row("fx-same", "ready"), title="fx title other")
    assert a["updatedAt"] == b["updatedAt"]

    state = fold_page(
        fold_page(new_read_state(), parse_envelope(page([a], "1"))),
        parse_envelope(page([b], "1")),
        requested_cursor=0,
    )

    assert any("unresolvable_tie:fx-same" in item for item in state.inconsistencies)
    assert state.items["fx-same"] == a, "first-seen is the documented tie-break"
    assert state.ties_resolved_first_seen == 1
    assert can_claim_complete(to_window(state)) is False


def test_declared_and_emitted_counts_are_separate():
    state = fold_page(new_read_state(), parse_envelope(page([row("fx-a"), row("fx-a2")], "2")))
    state = fold_page(state, parse_envelope(page([row("fx-a")], "3")), requested_cursor=2)

    window = to_window(state)
    assert window["scanned"] == 3
    assert window["count"] == 2


def test_terminal_walk_that_repeated_a_row_still_cannot_claim_the_whole_roster():
    """A cursor can repeat a row and still end cleanly; dedup must not launder that.

    Observed shape: a session inserted at the head pushes its predecessor onto
    the next page, so the walk finishes with `nextCursor: null` and one row seen
    twice. Nothing about that read proves the skipped row it may also contain.
    """
    state = fold_page(new_read_state(), parse_envelope(two_row_page()))
    state = fold_page(
        state,
        parse_envelope(page([row("fx-bravo"), row("fx-charlie")], None)),
        requested_cursor=2,
    )
    window = to_window(state)

    assert state.terminal_cursor_seen is True
    assert state.inconsistencies == (), "no arithmetic complaint to hide behind"
    assert state.duplicates_seen == 1
    assert window["scanned"] == 4 and window["count"] == 3
    assert can_claim_complete(window) is False
    assert can_claim_absence(window) is False


def test_valid_empty_roster_is_reported_as_empty_not_missing():
    state = fold_page(new_read_state(checked_at_ms=FIXTURE_NOW_MS), parse_envelope(empty_terminal_page()))
    window = to_window(state)

    assert window["count"] == 0
    assert read_status(window) == "empty_in_window"
    assert can_claim_absence(window) is True
    assert can_claim_complete(window) is True
