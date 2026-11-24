"""Read-window evidence: what this read is allowed to claim.

The vocabulary and the ordering rules are lifted from a discipline that already
exists in the office-hud front-end (`office-hud/web/src/deskTruth.ts`), whose
header documents the exact failure it was written to close: an audit answered
`status: "ok", count: 0, scanned: 375` with a window that had read 524288 bytes
of a 15755023-byte file and `truncated: true`. The count was true and the
absence was not. Reading `ok` as "nothing was ever asked" is the claim an
operator is most likely to believe, so it is the claim this module refuses to
make.

Names reused from that file: `count`, `scanned`, `truncated`, `checkedAt`, and
the status names `empty_in_window`, `window_truncated`, `unreadable`,
`no_answer`. Its `has_events` becomes `has_items` (a roster, not an event log)
and its `unparsed` has no analogue here, because rows missing required fields
are rejected at parse time rather than counted.

Names invented here, and provisional: `inconsistent`, `terminalCursorSeen`,
`duplicatesSeen`, `pagesFetched`, `cursorOffsets`, and the whole
completeness axis (`can_claim_complete`), which deskTruth does not have because
its source is a single file read rather than a paginated cursor walk.
"""

from __future__ import annotations

from typing import Literal, get_args

ReadStatus = Literal[
    "has_items",
    "empty_in_window",
    "window_truncated",
    "unreadable",
    "inconsistent",
    "no_answer",
]

#: `empty_in_window` is the only status that licenses "there are no sessions".
ABSENCE_LICENSE: ReadStatus = "empty_in_window"

#: A read may be complete only if it ran to a null cursor with nothing amiss.
#: Presence and completeness are separate axes: five rows recovered from a
#: drifting walk are five real rows, and are also not the whole roster.
_INCOMPLETE_STATUSES = ("unreadable", "no_answer", "inconsistent")


def read_status(window: object) -> ReadStatus:
    """Classify a read window. Mirrors `historyStatus()` ordering on purpose."""
    if not isinstance(window, dict):
        return "no_answer"

    # Trust the producer's own verdict about why a read failed; it knows and we
    # do not, and inferring "empty" from a failure is the original sin here.
    if window.get("status") == "unreadable" or window.get("ok") is False:
        return "unreadable"

    count = window.get("count")
    count = count if isinstance(count, int) and not isinstance(count, bool) else None

    # Presence is presence regardless of how far the read got.
    if count is not None and count > 0:
        return "has_items"

    # Everything below is a claim about an ABSENCE, and absence needs positive
    # evidence that the read finished. A payload with no window at all -- just
    # `{}` -- says nothing about the roster.
    if not isinstance(window.get("pagesFetched"), int) or window["pagesFetched"] == 0:
        # Nothing was read. deskTruth's analogue is a missing `window` object;
        # a cursor walk that never ran looks identical to an empty roster
        # otherwise, and "0 sessions" is the lie worth refusing here.
        return "no_answer"

    if not window.get("terminalCursorSeen"):
        return "window_truncated"

    if window.get("inconsistencies"):
        return "inconsistent"
    if count is None:
        return "no_answer"
    return "empty_in_window"


def can_claim_absence(window: object) -> bool:
    """Whether the read supports "there are no sessions"."""
    return read_status(window) == ABSENCE_LICENSE


def can_claim_complete(window: object) -> bool:
    """Whether the read supports "this is the entire roster".

    Deduplication alone never establishes it: a cursor walk can repeat rows
    (which dedup hides) and can skip rows (which nothing here can detect,
    because `list_chat_sessions` returns no declared total). So a duplicate is
    disqualifying rather than merely tidied.
    """
    if not isinstance(window, dict):
        return False
    status = read_status(window)
    if status in _INCOMPLETE_STATUSES:
        return False
    if not window.get("terminalCursorSeen"):
        return False
    if window.get("truncated") or window.get("cutOff"):
        return False
    duplicates = window.get("duplicatesSeen")
    if not isinstance(duplicates, int) or isinstance(duplicates, bool):
        return False
    return duplicates == 0 and not window.get("inconsistencies")


def read_label(window: object) -> str:
    """The sentence a human reads. No branch produces a bare absence.

    `deskTruth.ts` states this outright: "There is deliberately no branch that
    produces a bare 'no commands'." Same rule here.
    """
    status = read_status(window)
    count = window.get("count") if isinstance(window, dict) else None
    scanned = window.get("scanned") if isinstance(window, dict) else None
    pages = window.get("pagesFetched") if isinstance(window, dict) else None
    scanned_text = f" across {scanned} rows read" if isinstance(scanned, int) else ""

    if status == "has_items":
        return f"{count} session{'' if count == 1 else 's'} in the window that was read{scanned_text}."
    if status == "empty_in_window":
        return (
            f"No sessions in the {pages or '?'} page(s) that were read, "
            "and the cursor ran out. Absence applies to that read only."
        )
    if status == "window_truncated":
        return (
            f"No sessions in the {pages or '?'} page(s) that were read of a roster "
            "whose size is never declared. Sessions may exist outside the window."
        )
    if status == "inconsistent":
        why = ", ".join(str(i) for i in (window.get("inconsistencies") or []))
        return f"The cursor walk drifted ({why}); the roster is not known.{scanned_text}"
    if status == "unreadable":
        err = (window.get("error") if isinstance(window, dict) else None) or "no detail given"
        return f"The session list could not be read: {err}. This is not an absence of sessions."
    return "The session feed has not reported a read window."


def status_names() -> tuple[str, ...]:
    """Exposed so a test can assert the status vocabulary is not silently widened."""
    return get_args(ReadStatus)
