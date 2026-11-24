"""The real-sample differential test stays gated, and the gate is itself tested.

Real capture is not authorized, so this file must never fetch anything. It holds
two things: a skipped test that describes exactly what it would compare once a
sample exists, and assertions that the gate cannot open quietly.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "qoder_session_floor"
TESTS = Path(__file__).resolve().parent

CAPABLE_ROOTS = {
    "subprocess", "socket", "urllib", "http", "requests", "mcp", "os",
    "sys", "pathlib", "shutil", "asyncio", "importlib", "tempfile", "sqlite3",
}


def _roots_in(path: Path) -> set[str]:
    found: set[str] = set()
    for file in sorted(path.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module.split(".")[0])
    return found


def test_no_import_capture_capability_in_the_package():
    offenders = _roots_in(SRC) & CAPABLE_ROOTS
    assert offenders == set(), sorted(offenders)


def test_the_differential_test_is_skipped_not_deleted():
    """A gated test that silently disappears is a gate that already opened."""
    source = (TESTS / "test_real_sample_gate.py").read_text(encoding="utf-8")
    assert "gated: real capture not authorized" in source


@pytest.mark.skip(reason="gated: real capture not authorized")
def test_real_sample_matches_fixture_typewise():
    """Runs only once an authorized `list_chat_sessions` capture exists.

    It will compare field names, JSON types and optionality between the real
    envelope and `fixtures_synthetic`, and fail on any drift. It must still not
    write the sample into this repository without separate authorization.
    """
    raise AssertionError("unreachable while the gate is closed")
