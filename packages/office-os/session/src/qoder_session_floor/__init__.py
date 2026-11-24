"""Fixture-only contract layer for the Qoder in-app session feed.

Public surface:

    parse_envelope(raw, now_ms=None) -> Envelope
    new_read_state(...) / fold_page(state, page, requested_cursor) -> ReadState
    to_window(state) -> dict
    build_snapshot(state, now_ms=..., producer=...) -> dict
    serialize_snapshot(dict) -> str
    parse_snapshot(text, now_ms=...) -> dict
    validate_snapshot(dict, now_ms=...) -> list[str]
    status_label(raw) -> str
    read_status / can_claim_absence / can_claim_complete / read_label

No function here performs I/O of any kind: no MCP call, no network, no shell,
no file. That is enforced by tests/test_purity.py, not by convention.
"""

from .contract import (
    OBSERVED_ENVELOPE_FIELDS,
    OBSERVED_ENVELOPE_KIND,
    OBSERVED_RUNTIME_STATES,
    OBSERVED_SESSION_FIELDS,
)
from .envelope import Envelope, EnvelopeMalformed, parse_cursor, parse_envelope
from .evidence import (
    ReadStatus,
    can_claim_absence,
    can_claim_complete,
    read_label,
    read_status,
    status_names,
)
from .pagination import ReadState, fold_page, new_read_state, to_window
from .snapshot import (
    SCHEMA_VERSION,
    SchemaVersionMismatch,
    build_snapshot,
    parse_snapshot,
    serialize_snapshot,
    validate_snapshot,
)
from .states import UNKNOWN_LABEL, is_observed_state, status_label

__all__ = [
    "Envelope",
    "EnvelopeMalformed",
    "OBSERVED_ENVELOPE_FIELDS",
    "OBSERVED_ENVELOPE_KIND",
    "OBSERVED_RUNTIME_STATES",
    "OBSERVED_SESSION_FIELDS",
    "ReadState",
    "ReadStatus",
    "SCHEMA_VERSION",
    "SchemaVersionMismatch",
    "UNKNOWN_LABEL",
    "build_snapshot",
    "can_claim_absence",
    "can_claim_complete",
    "fold_page",
    "is_observed_state",
    "new_read_state",
    "parse_cursor",
    "parse_envelope",
    "parse_snapshot",
    "read_label",
    "read_status",
    "serialize_snapshot",
    "status_label",
    "status_names",
    "to_window",
    "validate_snapshot",
]
