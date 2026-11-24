"""Pure parsing of a captured `list_chat_sessions` envelope.

Nothing in this module can reach Qoder. It takes the JSON object an agent
already received and returns typed data or raises. That boundary is the whole
point: `mcp_call` is not an executable on this machine and there is no
importable client module for the conversation tools, so no script of any kind
can fetch this data by itself. A previous draft of this plan wrote
`from mcp_builtin_list_sessions import list_sessions` and `run(['mcp_call', ...])`;
neither symbol exists.

`EnvelopeMalformed` is *this package's* rejection of structurally invalid input.
It is not an upstream error shape: no failing response has ever been observed
from `list_chat_sessions`, so inventing an error envelope here would be a second
fabrication. Unknown-shaped input is refused, not modelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import (
    CURSOR_RE,
    OBSERVED_ENVELOPE_FIELDS,
    OBSERVED_ENVELOPE_KIND,
    OBSERVED_SESSION_FIELDS,
)

#: Fields a row must carry to be usable at all.
REQUIRED_ROW_FIELDS = tuple(OBSERVED_SESSION_FIELDS)

MIN_EPOCH_MS = 0


class EnvelopeMalformed(Exception):
    """Input is not a recognisable envelope. Carries a machine-readable reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Envelope:
    """One successfully parsed page."""

    items: tuple[dict[str, Any], ...]
    next_cursor: int | None
    emitted: int
    unexpected_row_fields: tuple[str, ...] = ()
    unexpected_envelope_fields: tuple[str, ...] = ()
    #: Rows whose `updatedAt` is structurally valid but not believable:
    #: epoch zero, or ahead of the caller's clock.
    suspicious_timestamp_count: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.next_cursor is None


def _is_int(value: Any) -> bool:
    """True int, excluding bool: `isinstance(True, int)` is True in Python, so a
    flag in a count field would otherwise pass as the number 1."""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_type(field_name: str, expected: str, value: Any, index: int) -> None:
    if expected == "str":
        if not isinstance(value, str):
            raise EnvelopeMalformed("row_type", f"row {index} {field_name} is not a string")
        return
    if expected == "int":
        if not _is_int(value) or value < 0:
            raise EnvelopeMalformed("row_type", f"row {index} {field_name} is not a non-negative int")
        return
    if expected == "int_ms":
        if not _is_int(value) or value < MIN_EPOCH_MS:
            raise EnvelopeMalformed("row_type", f"row {index} {field_name} is not a non-negative int")
        return
    if expected == "bool":
        if not isinstance(value, bool):
            raise EnvelopeMalformed("row_type", f"row {index} {field_name} is not a bool")
        return
    raise EnvelopeMalformed("contract_bug", f"no checker for declared type {expected}")


def parse_cursor(value: Any) -> int | None:
    """Validate a `nextCursor` exactly as the tool's input schema constrains it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise EnvelopeMalformed("cursor_type", "nextCursor is not a string or null")
    if not CURSOR_RE.match(value) or len(value) > 10:
        raise EnvelopeMalformed("cursor_format", f"nextCursor {value!r} is not a plain integer offset")
    return int(value)


def parse_envelope(raw: Any, *, now_ms: int | None = None) -> Envelope:
    """Parse one page of the observed envelope shape.

    Unknown extra keys -- on the envelope or on a row -- are preserved and
    reported rather than silently dropped or fatally rejected, so that upstream
    field additions show up as evidence instead of disappearing.
    """
    if not isinstance(raw, dict):
        raise EnvelopeMalformed("envelope_type", f"expected an object, got {type(raw).__name__}")

    kind = raw.get("kind")
    if kind is None:
        raise EnvelopeMalformed("envelope_missing_kind", "no `kind` key")
    if kind != OBSERVED_ENVELOPE_KIND:
        raise EnvelopeMalformed("envelope_kind_unknown", f"kind {kind!r} is not the observed contract")

    if "sessions" not in raw:
        raise EnvelopeMalformed("envelope_missing_sessions", "no `sessions` key")
    sessions = raw["sessions"]
    if not isinstance(sessions, list):
        raise EnvelopeMalformed("envelope_sessions_type", "`sessions` is not a list")

    rows: list[dict[str, Any]] = []
    unexpected_fields: set[str] = set()
    suspicious = 0

    for index, row in enumerate(sessions):
        if not isinstance(row, dict):
            raise EnvelopeMalformed("row_type", f"row {index} is not an object")
        for name, expected in OBSERVED_SESSION_FIELDS.items():
            if name not in row:
                raise EnvelopeMalformed("row_missing_field", f"row {index} lacks {name}")
            _check_type(name, expected, row[name], index)

        if row["sessionId"] == "":
            raise EnvelopeMalformed("row_identity", f"row {index} has an empty sessionId")

        unexpected_fields.update(k for k in row if k not in REQUIRED_ROW_FIELDS)

        # Kept as a flag, not a rejection: a 0 or a future stamp is a real
        # observation about an odd source, and discarding the row loses it.
        stamp = row["updatedAt"]
        if stamp == 0 or (now_ms is not None and stamp > now_ms):
            suspicious += 1

        rows.append(dict(row))

    if "nextCursor" not in raw:
        raise EnvelopeMalformed("envelope_missing_cursor", "no `nextCursor` key")
    next_cursor = parse_cursor(raw["nextCursor"])

    unexpected_envelope = {
        k for k in raw if k not in OBSERVED_ENVELOPE_FIELDS
    }

    return Envelope(
        items=tuple(rows),
        next_cursor=next_cursor,
        emitted=len(rows),
        unexpected_row_fields=tuple(sorted(unexpected_fields)),
        unexpected_envelope_fields=tuple(sorted(unexpected_envelope)),
        suspicious_timestamp_count=suspicious,
    )
