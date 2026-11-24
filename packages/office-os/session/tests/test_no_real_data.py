"""The fixture-only boundary, enforced on every test run rather than by hand.

S1's promise is that no real session data enters this repository. That was
verified once by an ad-hoc scan, which is worth nothing a week later: the scan
isn't re-run, and a future contributor pasting a captured payload into a fixture
would not be caught. So the promise becomes a test.

Two traps this file has to avoid, both recorded from real incidents:

1. **Self-reference.** The positive controls below inject a UUID-shaped id and a
   home-absolute path. Written as literals, those strings would trip the scan of
   this very file, so the suite could never be green -- and the tempting
   "fix" would be an exclusion list, which is how a guard stops guarding. The
   control values are therefore assembled at runtime from parts, and the
   detectors run over the repo *including* this file.
2. **A vacuous scan.** A detector that silently reads no files, or a smaller
   population than it claims, reports "clean" without having looked. So the
   scanned set is asserted by name against a census, and the serialized output
   of the fixture factories is scanned too -- a source-only grep cannot see a
   factory that fabricates a real-shaped identifier at runtime.

Whether the package can reach the conversation tools at all is enforced
separately by `test_purity.py`; nothing here re-states that claim.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Every path form that names a real home directory on a real machine. The
#: trailing component is optional on purpose: `str(Path.home())` yields
#: `/Users/<name>` with nothing after it, and requiring a trailing slash let a
#: bare home path -- the single most likely leak from a serializer -- slip past.
#: Found by injecting exactly that into `build_snapshot` and watching the guard
#: stay silent while an unrelated purity test caught the injection's syntax.
HOME_PATH_RE = re.compile(r"/" + "Users" + r"/[A-Za-z0-9._-]+")
HOME_PATH_RE2 = re.compile(r"/" + "home" + r"/[A-Za-z0-9._-]+")

#: Shape of a Qoder session id. Content matching this is a real identifier by
#: shape, whether or not it was captured.
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

SCANNED = (
    sorted((ROOT / "src").rglob("*.py"))
    + sorted((ROOT / "tests").glob("*.py"))
    + sorted((ROOT / "docs").rglob("*.md"))
    + [ROOT / "README.md", ROOT / "conftest.py", ROOT / "pyproject.toml"]
)


def _scan(text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in (("home_absolute_path", HOME_PATH_RE), ("posix_home_path", HOME_PATH_RE2), ("uuid_shaped_id", UUID_RE)):
        for match in pattern.findall(text):
            findings.append(f"{label}:{match[:24]}")
    return findings


def _scanned_blobs() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): path.read_text(encoding="utf-8") for path in SCANNED if path.exists()}


#: The scanned population, stated explicitly rather than inferred from the glob.
#: A `>= 18` floor was itself unenforceable: if the glob quietly stopped covering
#: one module, the remaining count assertions still passed and the scan reported
#: clean over a smaller population than it claimed to have read.
SRC_MODULES = {
    "__init__", "contract", "envelope", "evidence", "pagination", "snapshot", "states",
}
TEST_MODULES = {
    "fixtures_synthetic",
    "test_cursor_offset",
    "test_evidence_absence",
    "test_malformed_envelope",
    "test_no_real_data",
    "test_pagination_accumulation",
    "test_purity",
    "test_real_sample_gate",
    "test_snapshot_roundtrip",
    "test_states",
    "test_timestamps",
    "test_wire_shape",
}
CONFIG_FILES = {"README.md", "conftest.py", "pyproject.toml"}
#: Docs are asserted by name too. A census that pins src and tests but not docs
#: lets the scan quietly stop covering the one file most likely to quote real
#: observations -- which is precisely the shrinkage this test exists to catch.
DOC_FILES = {"docs/contract-session-list.md"}


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0]


def test_the_scanned_population_is_the_expected_census():
    """Every module must be scanned, by name, not by a count that could shrink."""
    blobs = _scanned_blobs()
    scanned_src = {_stem(Path(n).name) for n in blobs if n.startswith("src/")}
    scanned_tests = {_stem(Path(n).name) for n in blobs if n.startswith("tests/")}
    scanned_config = {n for n in blobs if not n.startswith(("src/", "tests/", "docs/"))}

    assert scanned_src == SRC_MODULES, {
        "missing": sorted(SRC_MODULES - scanned_src), "extra": sorted(scanned_src - SRC_MODULES)
    }
    assert scanned_tests == TEST_MODULES, {
        "missing": sorted(TEST_MODULES - scanned_tests), "extra": sorted(scanned_tests - TEST_MODULES)
    }
    assert scanned_config == CONFIG_FILES, scanned_config

    scanned_docs = {n for n in blobs if n.startswith("docs/")}
    assert scanned_docs == DOC_FILES, {
        "missing": sorted(DOC_FILES - scanned_docs), "extra": sorted(scanned_docs - DOC_FILES)
    }


def test_the_scanner_is_not_vacuous():
    """Prove the scan actually read content before trusting a clean verdict."""
    blobs = _scanned_blobs()
    total = sum(len(text) for text in blobs.values())
    assert total > 20_000, f"read only {total} chars; a truncated scan fakes cleanliness"
    # A display slice is not a scan: every file must contribute characters.
    thin = {name: len(text) for name, text in blobs.items() if len(text) < 20}
    assert thin == {}, thin


def test_generated_snapshot_text_is_clean_under_the_detector():
    """Scan what the code actually emits, not only what its source says.

    The source scan above cannot see a fixture factory that fabricates a
    real-shaped identifier at runtime. So a whole snapshot is serialized and run
    through the same detector.
    """
    import json

    import fixtures_synthetic as fx

    from qoder_session_floor import (
        build_snapshot,
        fold_page,
        new_read_state,
        parse_envelope,
        serialize_snapshot,
    )

    state = fold_page(
        new_read_state(checked_at_ms=fx.FIXTURE_NOW_MS),
        parse_envelope(fx.four_state_page()),
    )
    text = serialize_snapshot(build_snapshot(state, now_ms=fx.FIXTURE_NOW_MS, producer="synthetic"))
    assert _scan(text) == [], _scan(text)
    assert json.loads(text)["sessions"], "an empty snapshot would pass vacuously"


def test_the_detector_fires_on_injected_real_data():
    """Positive control, with values assembled at runtime so this file stays clean."""
    uuid = "-".join(["01234567", "89ab", "cdef", "0123", "456789abcdef"])
    home = "/" + "Users" + "/" + "someone" + "/Documents/Qoder/2026-01-01/" + "abcd1234"
    bare = "/" + "Users" + "/" + "someone"
    assert _scan(f'sessionId="{uuid}"') == ["uuid_shaped_id:" + uuid[:24]]
    assert _scan(f'cwd="{home}"')
    assert _scan(home.replace("/Users/", "/home/"))
    # The bare form is what `str(Path.home())` produces. Without this case the
    # pattern could require a trailing component and every control would still
    # pass, which is exactly how the narrow version of this detector survived a
    # mutation sweep.
    assert _scan(f'producerHome="{bare}"'), "a home path with nothing after it must be caught"
    assert _scan(bare.replace("/Users/", "/home/")), "same for the posix form"


def test_the_detector_is_silent_on_the_fixture_shape():
    """Must-differ control: the clean fixture must not look like real data.

    Without this, a detector that flags everything would pass the injection test
    and still be useless.
    """
    clean = 'cwd="/fixture/qoder-session-floor/fx-alpha", sessionId="fx-alpha"'
    assert _scan(clean) == []


def test_no_repository_file_carries_real_data():
    offenders = {}
    for name, text in _scanned_blobs().items():
        found = _scan(text)
        if found:
            offenders[name] = sorted(set(found))
    assert offenders == {}, offenders


def test_generated_fixture_values_are_all_marked_synthetically():
    """Behavioural, not a grep: run the fixture factories and inspect what comes out.

    A literal scan of `fixtures_synthetic.py` would pass vacuously, because the
    module builds rows from arguments rather than writing `"sessionId": "..."`
    literals. So this calls the factory and checks the produced values.
    """
    import fixtures_synthetic as fx

    import json

    produced = [fx.row("fx-check"), fx.one_row_page(), fx.two_row_page(), fx.terminal_page()]
    rows = fx.two_row_page()["sessions"]
    ids = [row["sessionId"] for row in rows] + ["fx-check"]
    titles = [row["title"] for row in rows]
    cwds = [row["cwd"] for row in rows]

    assert all(i.startswith("fx-") for i in ids), ids
    assert all("fx" in t for t in titles), titles
    assert all(c.startswith("/fixture/") for c in cwds), cwds
    # Backup for the whole-snapshot scan above: each row is detector-checked on its
    # own, so deleting that one assertion cannot silently drop runtime coverage.
    for row in rows:
        assert _scan(json.dumps(row)) == [], row
    assert produced, "the factories must yield something for this to mean anything"
    assert "SYNTHETIC" in (ROOT / "tests" / "fixtures_synthetic.py").read_text(encoding="utf-8").upper()
