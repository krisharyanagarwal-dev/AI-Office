"""Field-level contract for the Qoder session-list envelope.

Everything here is split by provenance. `OBSERVED_*` describes what a real
`list_chat_sessions` response was seen to contain; `PROPOSED_*` describes names
this package invented and which no upstream contract guarantees yet. A reviewer
should be able to delete every PROPOSED symbol without invalidating an
observation.

Observation provenance (recorded 2026-10-16/17 in chat session
3a6e7682, from four calls to the in-session MCP tool
`mcp__builtin__list_chat_sessions`):

    limit=50, archived omitted -> 42 sessions, nextCursor null
    limit=1                    -> 1 session,  nextCursor "1"
    limit=2                    -> 2 sessions, nextCursor "2"
    limit=1, archived=true     -> 1 session,  nextCursor "1", archived true

No captured production payload is stored in this repository, and none of the
fixture rows below are real sessions.
"""

from __future__ import annotations

import re
from typing import Final

#: The only envelope `kind` ever observed.
OBSERVED_ENVELOPE_KIND: Final = "qoder.chatSessions.listed"

#: Observed per-session field names and their observed JSON types.
#:
#: `int_ms` means an integer number of milliseconds since the epoch: the values
#: are 13 digits, and reading one as seconds overflows the representable year
#: range, so the unit is forced by the observation rather than chosen here.
OBSERVED_SESSION_FIELDS: Final[dict[str, str]] = {
    "sessionId": "str",
    "title": "str",
    "cwd": "str",
    "updatedAt": "int_ms",
    "runtimeState": "str",
    "pendingInteractionCount": "int",
    "unread": "bool",
    "archived": "bool",
}

#: Envelope keys observed at the top level.
OBSERVED_ENVELOPE_FIELDS: Final[dict[str, str]] = {
    "kind": "str",
    "sessions": "list",
    "nextCursor": "str_or_null",
}

#: Runtime states observed in a real response. Not a claim that this is the
#: complete vocabulary -- see `states.status_label`, which must never assume it is.
OBSERVED_RUNTIME_STATES: Final[frozenset[str]] = frozenset(
    {"running", "ready", "waiting-user", "cold"}
)

#: Cursor grammar from the tool's own input schema (`^\\d+$`, max 10 chars).
#: Leading zeros are rejected as a PROPOSED tightening: "01" was never observed.
CURSOR_RE: Final = re.compile(r"^(?:0|[1-9]\d*)$")

# --- PROPOSED: invented by this package, not observed upstream. ----------------
#
# PROPOSED_SNAPSHOT_GENERATED_AT   int-ms clock stamp, unit pinned explicitly
# PROPOSED_SNAPSHOT_SCHEMA_VERSION version integer for the serialized snapshot
# PROPOSED_WINDOW_*                read-window evidence keys (see evidence.py)
# PROPOSED_QODER_RUNTIME_STATE     rename of `runtimeState`, to stop a vocabulary
#                                  collision: the office-hud server already ships
#                                  a `runtimeState` whose values are
#                                  busy/idle/offline/breaker/error/UNKNOWN
#                                  (office-hud/server/lib/dots/systems/*.js).
#                                  Sharing the old name across two populations
#                                  would let one floor's states color another's
#                                  desks. Renaming is a proposal, not a fact.
