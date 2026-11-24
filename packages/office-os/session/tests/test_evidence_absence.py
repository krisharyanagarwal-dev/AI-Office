"""Requirements 7, 8 and 14: absence needs evidence, and an unfinished window discloses itself.

Ported discipline from `office-hud/web/src/deskTruth.ts`, whose header records
the incident this guards: an audit returned `status: "ok", count: 0, scanned:
375` over 524288 of 15755023 bytes with `truncated: true`. The count was
correct and the absence it seemed to prove was not.
"""

import pytest

from qoder_session_floor import (
    can_claim_absence,
    can_claim_complete,
    read_label,
    read_status,
    status_names,
)

HAS_ITEMS = {"count": 2, "scanned": 2, "pagesFetched": 1, "terminalCursorSeen": True, "duplicatesSeen": 0, "inconsistencies": []}
EMPTY_IN_WINDOW = {"count": 0, "scanned": 0, "pagesFetched": 1, "terminalCursorSeen": True, "duplicatesSeen": 0, "inconsistencies": []}
WINDOW_TRUNCATED = {"count": 0, "scanned": 0, "pagesFetched": 2, "terminalCursorSeen": False, "duplicatesSeen": 0, "inconsistencies": []}
UNREADABLE = {"ok": False, "error": "producer said no", "count": 0, "pagesFetched": 3, "terminalCursorSeen": False}
INCONSISTENT = {"count": 0, "scanned": 4, "pagesFetched": 2, "terminalCursorSeen": True, "duplicatesSeen": 1, "inconsistencies": ["cursor_jump:asked=1:expected=2"]}
NO_ANSWER = {}

CASES = {
    "has_items": HAS_ITEMS,
    "empty_in_window": EMPTY_IN_WINDOW,
    "window_truncated": WINDOW_TRUNCATED,
    "unreadable": UNREADABLE,
    "inconsistent": INCONSISTENT,
    "no_answer": NO_ANSWER,
}


def test_an_untouched_read_is_no_answer_not_an_empty_roster():
    """`pagesFetched: 0` means nothing was read.

    Without this case the zero-pages branch is only reachable via a *missing*
    key, and a mutant that disables the explicit `== 0` check survives -- which
    is exactly how "we never ran" comes to read as "nobody is home".
    """
    from qoder_session_floor import new_read_state, to_window

    window = to_window(new_read_state())
    assert window["pagesFetched"] == 0
    assert read_status(window) == "no_answer"
    assert can_claim_absence(window) is False

    explicit_zero = dict(NO_ANSWER, pagesFetched=0, count=0, scanned=0, terminalCursorSeen=False)
    assert read_status(explicit_zero) == "no_answer"
    assert can_claim_absence(explicit_zero) is False


@pytest.mark.parametrize("expected", sorted(CASES))
def test_each_window_classifies_to_the_intended_status(expected):
    assert read_status(CASES[expected]) == expected


def test_absence_is_claimable_in_exactly_one_status():
    """The gate has one open position, and that is the whole design."""
    claimable = {name for name, window in CASES.items() if can_claim_absence(window)}
    assert claimable == {"empty_in_window"}


@pytest.mark.parametrize("name", ["window_truncated", "unreadable", "inconsistent", "no_answer"])
def test_no_incomplete_window_can_support_an_absence_claim(name):
    assert can_claim_absence(CASES[name]) is False


def test_no_label_is_a_bare_absence():
    """deskTruth: "There is deliberately no branch that produces a bare
    'no commands'." A reader must see what was searched, not just what was found."""
    for name, window in CASES.items():
        label = read_label(window)
        assert label.strip(), name
        assert label != "No sessions.", name
        assert not label.lower().startswith("no sessions. "), name


def test_empty_in_window_label_states_the_scope_of_the_claim():
    label = read_label(EMPTY_IN_WINDOW)
    assert "page" in label and "read" in label
    assert "Absence applies to that read only" in label


def test_truncated_label_refuses_to_extrapolate():
    assert "may exist outside the window" in read_label(WINDOW_TRUNCATED)


def test_unreadable_label_says_this_is_not_an_absence():
    assert "not an absence" in read_label(UNREADABLE)


def test_drifted_label_admits_the_roster_is_unknown():
    assert "not known" in read_label(INCONSISTENT)


def test_absence_of_the_window_object_is_not_zero_sessions():
    """`{}` must never read as an empty roster -- the exact `{}` case deskTruth calls out."""
    assert read_status({}) == "no_answer"
    assert read_status(None) == "no_answer"
    assert read_status("count: 0") == "no_answer"
    assert can_claim_absence({}) is False


def test_missing_or_truncated_window_blocks_completeness_even_with_rows():
    partial = {"count": 5, "scanned": 5, "pagesFetched": 1, "terminalCursorSeen": False, "duplicatesSeen": 0, "inconsistencies": []}
    assert read_status(partial) == "has_items", "five rows really were seen"
    assert can_claim_complete(partial) is False, "and they are still not the roster"


def test_deduplicated_walk_is_incomplete_by_construction():
    """Requirement 14's central case: tidied duplicates are not a full roster."""
    assert can_claim_complete(INCONSISTENT) is False
    clean = dict(INCONSISTENT, inconsistencies=[], duplicatesSeen=0)
    assert can_claim_complete(clean) is True, "control: the gate does open when the walk is sound"


def test_duplicates_reject_completeness_when_nothing_else_is_wrong():
    """The only thing standing between this window and a completeness claim is
    `duplicatesSeen`. Without this case that branch is unreachable, because
    every other drifting fixture also carries an inconsistency or a missing
    terminal cursor -- and an unreachable guard is a guard that can be deleted
    without any test noticing."""
    drift_terminal = {
        "count": 3,
        "scanned": 4,
        "pagesFetched": 2,
        "terminalCursorSeen": True,
        "duplicatesSeen": 1,
        "identicalDuplicates": 0,
        "cutOff": False,
        "truncated": False,
        "inconsistencies": [],
    }
    assert read_status(drift_terminal) == "has_items"
    assert can_claim_complete(drift_terminal) is False
    assert can_claim_complete(dict(drift_terminal, duplicatesSeen=0, scanned=3)) is True


def test_completeness_gate_rejects_a_missing_duplicates_field():
    """Absence of the evidence is not the same as zero duplicates."""
    assert can_claim_complete({"count": 1, "pagesFetched": 1, "terminalCursorSeen": True}) is False


def test_status_vocabulary_is_not_silently_widened():
    assert set(status_names()) == set(CASES)
