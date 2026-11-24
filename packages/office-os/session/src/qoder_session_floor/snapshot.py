"""Snapshot assembly, validation and serialization.

Serialized rows carry `qoderRuntimeState` (the upstream value, verbatim) and
`statusLabel` (this package's PROPOSED label). The upstream key name
`runtimeState` is deliberately *not* re-emitted: the office-hud server already
publishes a `runtimeState` for opencode fleet agents whose vocabulary is
`busy`/`idle`/`offline`/`breaker`/`error`/`UNKNOWN`, so reusing the old name
across two populations would let fleet states color Qoder desks.

Field-name provenance is embedded in every snapshot under `provenance`, because
a reader of the file cannot otherwise tell an observed key from an invented one.
"""

from __future__ import annotations

import json
from typing import Any, Final

from .contract import (
    OBSERVED_ENVELOPE_KIND,
    OBSERVED_RUNTIME_STATES,
    OBSERVED_SESSION_FIELDS,
)
from .evidence import can_claim_absence, can_claim_complete, read_status
from .pagination import ReadState, to_window
from .states import PROVISIONAL_STATUS_LABELS, UNKNOWN_LABEL, status_label

#: PROPOSED. Versioning exists because an silently-mis-parsed snapshot is the
#: same failure class as an absence claim from a partial read.
SCHEMA_VERSION: Final = 1
SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({SCHEMA_VERSION})

#: PROPOSED allowance for a source clock ahead of ours. Zero means "any row from
#: the future is suspicious", which is almost certainly too strict for real
#: capture, where sub-second skew across processes is normal.
DEFAULT_CLOCK_SKEW_MS: Final = 0

_ROW_ORDER_KEY = "sessionId"


class SchemaVersionMismatch(Exception):
    """Serialized snapshot was written under a version this code cannot parse."""

    def __init__(self, found: object) -> None:
        super().__init__(f"snapshot schemaVersion {found!r} is not in {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
        self.found = found


def decorate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Add the PROPOSED layer to one verbatim upstream row."""
    raw_state = row["runtimeState"]
    out = {
        "sessionId": row["sessionId"],
        "title": row["title"],
        "cwd": row["cwd"],
        "updatedAt": row["updatedAt"],
        "pendingInteractionCount": row["pendingInteractionCount"],
        "unread": row["unread"],
        "archived": row["archived"],
        # Renamed (PROPOSED) and preserved verbatim -- never normalised here.
        "qoderRuntimeState": raw_state,
        "statusLabel": status_label(raw_state),
    }
    for key, value in row.items():
        if key not in out and key != "runtimeState":
            out.setdefault("unexpectedFields", {})[key] = value
    return out


def build_snapshot(
    state: ReadState,
    *,
    now_ms: int,
    producer: str,
) -> dict[str, Any]:
    """Assemble the serialized snapshot from an accumulated read."""
    window = to_window(state)
    rows = sorted((decorate_row(row) for row in state.items.values()), key=lambda r: r["sessionId"])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "observedAtMs": now_ms,
        "producer": producer,
        "source": {
            "tool": "mcp__builtin__list_chat_sessions",
            "envelopeKind": OBSERVED_ENVELOPE_KIND,
            "paginationVerified": "small-limit offset arithmetic only; multi-page beyond limit=2 never exercised",
        },
        "provenance": {
            "observedUpstreamFields": sorted(OBSERVED_SESSION_FIELDS),
            "proposedFields": [
                "schemaVersion",
                "observedAtMs",
                "producer",
                "source",
                "provenance",
                "evidence",
                "qoderRuntimeState",
                "statusLabel",
            ],
            "proposedStatusLabels": dict(sorted(PROVISIONAL_STATUS_LABELS.items())),
            "unknownLabel": UNKNOWN_LABEL,
            "observedRuntimeStates": sorted(OBSERVED_RUNTIME_STATES),
        },
        "evidence": window,
        "claims": {
            "canClaimAbsence": can_claim_absence(window),
            "canClaimComplete": can_claim_complete(window),
            "readStatus": read_status(window),
        },
        "sessions": rows,
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_snapshot(snapshot: Any, *, now_ms: int, clock_skew_ms: int = DEFAULT_CLOCK_SKEW_MS) -> list[str]:
    """Return machine-readable problems. Raises only on a version mismatch.

    Problems are collected rather than raised so a caller can report "3 rows are
    suspicious" instead of aborting on the first one, but a version this code
    cannot interpret is a hard stop: parsing past it is how a schema change
    becomes silent data loss.
    """
    if not isinstance(snapshot, dict):
        raise SchemaVersionMismatch(None)

    found = snapshot.get("schemaVersion")
    # A non-integer version is a mismatch, not a lookup: `[] in frozenset({1})`
    # raises TypeError, and a validator that crashes on odd input is worse than
    # one that refuses it.
    if not isinstance(found, int) or isinstance(found, bool) or found not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaVersionMismatch(found)

    problems: list[str] = []
    evidence = snapshot.get("evidence")
    sessions = snapshot.get("sessions")

    if not isinstance(evidence, dict):
        problems.append("missing_evidence_window")
    if not isinstance(sessions, list):
        problems.append("sessions_not_a_list")
        return problems

    if isinstance(evidence, dict):
        if evidence.get("count") != len(sessions):
            problems.append("count_does_not_match_sessions")
        if not evidence.get("terminalCursorSeen"):
            problems.append("window_not_terminal")

    if not _is_int(snapshot.get("observedAtMs")):
        problems.append("observedAtMs_not_int_ms")

    seen: set[str] = set()
    for index, row in enumerate(sessions):
        if not isinstance(row, dict):
            problems.append(f"row_{index}_not_object")
            continue
        session_id = row.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            problems.append(f"row_{index}_missing_identity")
            continue
        if session_id in seen:
            # A serialized snapshot with duplicate ids cannot be produced by
            # fold_page; this catches hand-edited or merged files.
            problems.append(f"duplicate_sessionId:{session_id}")
        seen.add(session_id)

        raw_state = row.get("qoderRuntimeState")
        if raw_state is None:
            problems.append(f"row_{index}_missing_qoderRuntimeState")
        elif row.get("statusLabel") != status_label(raw_state):
            problems.append(f"row_{index}_statusLabel_not_derived_from_state")

        stamp = row.get("updatedAt")
        if not _is_int(stamp):
            problems.append(f"row_{index}_updatedAt_not_int_ms")
        elif stamp == 0:
            problems.append(f"row_{index}_epoch_zero_timestamp")
        elif stamp > now_ms + clock_skew_ms:
            problems.append(f"row_{index}_timestamp_from_the_future")

        if not isinstance(row.get("archived"), bool):
            problems.append(f"row_{index}_archived_not_bool")
        if "runtimeState" in row:
            # The collision this schema rename exists to avoid.
            problems.append(f"row_{index}_carries_forbidden_runtimeState_key")

    return problems


def serialize_snapshot(snapshot: dict[str, Any]) -> str:
    """Deterministic text: same data in, same bytes out."""
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_snapshot(text: str, *, now_ms: int) -> dict[str, Any]:
    """Deserialize and validate. Raises on version mismatch or invalid JSON."""
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"snapshot is not valid JSON: {error.msg}") from error
    problems = validate_snapshot(loaded, now_ms=now_ms)
    if problems:
        raise ValueError("snapshot failed validation: " + "; ".join(problems))
    return loaded
