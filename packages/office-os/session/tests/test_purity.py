"""Enforced boundary: the package cannot reach Qoder, the network, a shell, or a file.

The superseded plan's central fiction was a Python feed writer that did
`from mcp_builtin_list_sessions import list_sessions` and `run(['mcp_call', ...])`
-- neither symbol exists on this machine, because the conversation tools are only
reachable from inside a Qoder agent turn. So purity is asserted by walking the
AST rather than promised in a docstring, and the detector is proven against an
injected violation before its own clean verdict means anything.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "qoder_session_floor"

#: Standard-library modules that do no I/O.
ALLOWED_IMPORT_ROOTS = {"__future__", "dataclasses", "typing", "re", "json"}

#: Named explicitly so a future "convenience" import fails loudly here.
FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "input"}

#: Substrings that mark a call aimed at the conversation tools themselves.
CAPABILITY_MARKERS = ("chat_session", "mcp")


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # intra-package relative import
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _escape_hatches(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in FORBIDDEN_CALLS:
                found.add(func.id)
            if any(marker in func.id.lower() for marker in CAPABILITY_MARKERS):
                found.add(func.id)
        elif isinstance(func, ast.Attribute):
            if func.attr in {"popen", "system", "spawn", "connect", "request"}:
                found.add(func.attr)
            if any(marker in func.attr.lower() for marker in CAPABILITY_MARKERS):
                found.add(func.attr)
        # A tool invoked by name -- `client.call_tool("list_chat_sessions")` --
        # hides the capability in an argument, so arguments are scanned too.
        for arg in list(node.args) + [keyword.value for keyword in node.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if any(marker in arg.value.lower() for marker in CAPABILITY_MARKERS):
                    found.add(f"tool_name:{arg.value}")
    return found


def _code_tokens(source: str) -> set[str]:
    """Names, attributes and string constants that are *not* docstrings.

    Prose in this package deliberately names the forbidden symbols to explain
    why they are forbidden; only code must not.
    """
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))

    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, ast.alias):
            tokens.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            tokens.add(node.value)
    return tokens


def _scan_source(source: str) -> set[str]:
    findings: set[str] = set()
    tree = ast.parse(source)
    findings |= {f"import:{root}" for root in _import_roots(tree) - ALLOWED_IMPORT_ROOTS}
    findings |= {f"call:{name}" for name in _escape_hatches(tree)}
    return findings


def test_the_detector_fires_on_an_injected_violation():
    """Positive control: a detector that never fires proves nothing."""
    mutant = "import subprocess\nimport socket\nsubprocess.run(['ls'])\nopen('x')\n"
    findings = _scan_source(mutant)
    assert "import:subprocess" in findings
    assert "import:socket" in findings
    assert "call:open" in findings


def test_the_detector_fires_on_an_mcp_shaped_call():
    mutant = "def fetch():\n    return list_chat_sessions(limit=50)\n"
    assert "call:list_chat_sessions" in _scan_source(mutant)


def test_the_detector_fires_on_an_attribute_form_tool_call():
    mutant = "def fetch():\n    return client.call_tool('list_chat_sessions')\n"
    findings = _scan_source(mutant)
    assert any("chat_session" in item for item in findings), findings


@pytest.mark.parametrize("path", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_no_module_imports_anything_capable_of_io(path):
    assert _scan_source(path.read_text(encoding="utf-8")) == set(), path.name


@pytest.mark.parametrize("path", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_allowed_imports_are_exactly_the_io_free_ones(path):
    roots = _import_roots(ast.parse(path.read_text(encoding="utf-8")))
    assert roots <= ALLOWED_IMPORT_ROOTS, path.name


def test_the_package_never_names_an_executable_mcp_path_in_code():
    """`mcp_call` is not a binary here and there is no client module to import.

    Prose may name it to explain that; code may not.
    """
    for path in sorted(SRC.glob("*.py")):
        tokens = _code_tokens(path.read_text(encoding="utf-8"))
        assert not any("mcp_call" in token for token in tokens), path.name
        assert "mcp_builtin_list_sessions" not in tokens, path.name
        assert not any(token.startswith("import mcp") for token in tokens), path.name


def test_provenance_reference_to_the_tool_is_a_string_not_a_call():
    """The snapshot records *which* tool produced it; it must not call it."""
    blob = (SRC / "snapshot.py").read_text(encoding="utf-8")
    assert "mcp__builtin__list_chat_sessions" in blob
    assert "list_chat_sessions(" not in blob
