"""SYNTHETIC fixtures. Every value in this file is invented.

No real session title, identifier, working directory or roster content appears
here, and none may be added: real capture is not authorized. The shapes mirror
the observed envelope field names and the observed offset arithmetic, because
that is the part under test -- not the contents.

Fixture ids are prefixed `fx-` on purpose so a grep for them can prove the
absence of real data.
"""

from __future__ import annotations

from typing import Any

FIXTURE_NOTE = "synthetic fixture, not a captured sample"

#: A wall clock every fixture is measured against, so tests are deterministic.
FIXTURE_NOW_MS = 1_792_200_000_000

KIND = "qoder.chatSessions.listed"


def row(
    session_id: str,
    runtime_state: str = "running",
    updated_at: int = FIXTURE_NOW_MS,
    **overrides: Any,
) -> dict[str, Any]:
    """One session row in the observed eight-field upstream shape."""
    base: dict[str, Any] = {
        "sessionId": session_id,
        "title": f"fx title {session_id}",
        "cwd": f"/fixture/qoder-session-floor/{session_id}",
        "updatedAt": updated_at,
        "runtimeState": runtime_state,
        "pendingInteractionCount": 0,
        "unread": False,
        "archived": False,
    }
    base.update(overrides)
    return base


def page(
    rows: list[dict[str, Any]],
    next_cursor: str | None = None,
    *,
    kind: str = KIND,
) -> dict[str, Any]:
    """One envelope page, in the observed `{kind, sessions, nextCursor}` shape."""
    return {"kind": kind, "sessions": rows, "nextCursor": next_cursor}


def one_row_page() -> dict[str, Any]:
    """Reproduces the observed `limit=1 -> nextCursor "1"` arithmetic."""
    return page([row("fx-alpha")], "1")


def two_row_page() -> dict[str, Any]:
    """Reproduces the observed `limit=2 -> nextCursor "2"` arithmetic."""
    return page([row("fx-alpha"), row("fx-bravo")], "2")


def terminal_page(start_at: int = 2, count: int = 2) -> dict[str, Any]:
    """A final page: rows delivered and a null cursor, as `limit=50` returned."""
    rows = [row(f"fx-id-{index}") for index in range(start_at, start_at + count)]
    return page(rows, None)


def empty_terminal_page() -> dict[str, Any]:
    """Valid empty input: a finished read of nothing."""
    return page([], None)


def four_state_page() -> dict[str, Any]:
    """One row per runtime state actually observed upstream."""
    return page(
        [
            row("fx-running", "running"),
            row("fx-ready", "ready"),
            row("fx-waiting", "waiting-user"),
            row("fx-cold", "cold"),
        ],
        None,
    )
