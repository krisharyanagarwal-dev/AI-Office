"""Cursor accumulation as a pure reducer over captured pages.

Pagination semantics were observed, not assumed: `limit=1` returned
`nextCursor "1"` and `limit=2` returned `nextCursor "2"`, while a `limit=50`
call over 42 sessions returned `null`. `nextCursor` is therefore an **item
offset** -- the number of rows consumed -- not a page index. A page counter is
the wrong arithmetic: with `limit=50` it sends `"2"` where `"50"` is required,
re-reads the first page, and double-counts the roster. A previous draft of this
plan did exactly that.

What this module can and cannot prove: a repeated row is detectable, a
non-advancing or jumped cursor is detectable, and arithmetic disagreement
between a page's length and its advertised next offset is detectable. A *skipped*
row is not detectable at all, because `list_chat_sessions` declares no total
count. So this reducer never converts "no duplicates" into "the whole roster";
that judgement lives in `evidence.can_claim_complete`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .envelope import Envelope

#: PROPOSED and arbitrary: a guard against a cursor that never terminates, not a
#: tuning parameter. Nothing upstream suggests a real page ceiling.
DEFAULT_MAX_PAGES = 20


@dataclass(frozen=True)
class ReadState:
    """Accumulated result of a cursor walk. Treat as immutable; `fold_page`
    returns a new state rather than mutating one."""

    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    cursor_offsets: tuple[int, ...] = ()
    pages_fetched: int = 0
    items_declared: int = 0
    duplicates_seen: int = 0
    identical_duplicates: int = 0
    ties_resolved_first_seen: int = 0
    terminal_cursor_seen: bool = False
    cut_off: bool = False
    inconsistencies: tuple[str, ...] = ()
    unexpected_row_fields: tuple[str, ...] = ()
    suspicious_timestamp_count: int = 0
    expected_next_cursor: int | None = 0
    max_pages: int = DEFAULT_MAX_PAGES
    checked_at_ms: int | None = None

    @property
    def finished(self) -> bool:
        return self.terminal_cursor_seen or self.cut_off


def new_read_state(*, max_pages: int = DEFAULT_MAX_PAGES, checked_at_ms: int | None = None) -> ReadState:
    return ReadState(max_pages=max_pages, checked_at_ms=checked_at_ms)


def _record(items: list[str], reason: str) -> None:
    if reason not in items:
        items.append(reason)


def fold_page(state: ReadState, page: Envelope, requested_cursor: int | None = None) -> ReadState:
    """Merge one parsed page into the accumulated read.

    `requested_cursor` is the offset this page was asked for; `None` on the
    first page means offset 0.
    """
    offset = 0 if requested_cursor is None else requested_cursor
    items = dict(state.items)
    inconsistencies = list(state.inconsistencies)
    unexpected = set(state.unexpected_row_fields)

    duplicates = state.duplicates_seen
    identical = state.identical_duplicates
    ties = state.ties_resolved_first_seen

    if state.terminal_cursor_seen:
        # A row delivered after the null cursor means the roster moved under
        # the walk. It is real data, but no arithmetic here can place it.
        _record(inconsistencies, "page_after_terminal")

    if state.pages_fetched and offset != state.expected_next_cursor:
        _record(
            inconsistencies,
            f"cursor_jump:asked={offset}:expected={state.expected_next_cursor}",
        )

    if offset in state.cursor_offsets:
        _record(inconsistencies, f"non_advancing_cursor:{offset}")

    for row in page.items:
        session_id = row["sessionId"]
        existing = items.get(session_id)
        if existing is None:
            items[session_id] = dict(row)
            continue

        duplicates += 1
        newer = row["updatedAt"]
        older = existing["updatedAt"]
        if newer > older:
            # Deterministic: the freshest observation of an id wins outright.
            items[session_id] = dict(row)
        elif newer == older and row == existing:
            identical += 1
        elif newer == older:
            # Same stamp, different content: unresolvable from the data alone.
            # Keeping first-seen makes the outcome reproducible, not correct.
            _record(inconsistencies, f"unresolvable_tie:{session_id}")
            ties += 1
        # else: a strictly older duplicate arrives late, which only happens when
        # the list re-sorted mid-walk; keep the newer row and mark the drift.

    unexpected.update(page.unexpected_row_fields)

    terminal = page.is_terminal
    expected_next = state.expected_next_cursor
    if not terminal:
        arithmetic = offset + page.emitted
        if page.next_cursor != arithmetic:
            _record(
                inconsistencies,
                f"offset_mismatch:cursor={page.next_cursor}:arithmetic={arithmetic}",
            )
        expected_next = page.next_cursor

    if page.emitted == 0 and not terminal:
        _record(inconsistencies, "empty_page_continuation")

    pages_fetched = state.pages_fetched + 1
    cut_off = state.cut_off or (not terminal and pages_fetched >= state.max_pages)

    return replace(
        state,
        items=items,
        cursor_offsets=state.cursor_offsets + (offset,),
        pages_fetched=pages_fetched,
        items_declared=state.items_declared + page.emitted,
        duplicates_seen=duplicates,
        identical_duplicates=identical,
        ties_resolved_first_seen=ties,
        terminal_cursor_seen=state.terminal_cursor_seen or terminal,
        cut_off=cut_off,
        inconsistencies=tuple(inconsistencies),
        unexpected_row_fields=tuple(sorted(unexpected)),
        suspicious_timestamp_count=state.suspicious_timestamp_count + page.suspicious_timestamp_count,
        expected_next_cursor=expected_next,
    )


def to_window(state: ReadState) -> dict[str, Any]:
    """The read-window evidence object consumed by `evidence.py`.

    `count` is unique rows emitted; `scanned` is rows read before dedup, so
    `scanned > count` is itself the duplication signal.
    """
    return {
        "ok": True,
        "status": "read",
        "error": None,
        "count": len(state.items),
        "scanned": state.items_declared,
        "pagesFetched": state.pages_fetched,
        "cursorOffsets": list(state.cursor_offsets),
        "terminalCursorSeen": state.terminal_cursor_seen,
        "duplicatesSeen": state.duplicates_seen,
        "identicalDuplicates": state.identical_duplicates,
        "cutOff": state.cut_off,
        "truncated": state.cut_off or not state.terminal_cursor_seen,
        "inconsistencies": list(state.inconsistencies),
        "unexpectedRowFields": list(state.unexpected_row_fields),
        "suspiciousTimestampCount": state.suspicious_timestamp_count,
        "checkedAt": state.checked_at_ms,
    }
