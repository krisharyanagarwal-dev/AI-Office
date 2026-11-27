"""Tests for web_search skill."""

from __future__ import annotations

from pathlib import Path

import pytest

import sys as _sys

if str(Path(__file__).resolve().parents[1]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import web_search  # noqa: E402
from skills.registry import get_registry  # noqa: E402


SAMPLE_HTML = """
<html>
  <body>
    <a rel="nofollow" class="result__a" href="https://example.com/a">Example A</a>
    <a class="result__snippet" href="#">This is snippet A about markets.</a>
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fb">Example B</a>
    <span class="result__snippet">Snippet B with NSE data.</span>
    <a rel="nofollow" class="result__a" href="https://example.com/c">Example C</a>
  </body>
</html>
"""


class TestWebSearchManifest:
    """Skill manifest is valid and registered."""

    def test_manifest_exists(self):
        assert hasattr(web_search, "SKILL_MANIFEST")
        manifest = web_search.SKILL_MANIFEST
        assert manifest["name"] == "web_search"
        assert manifest["version"] == "1.0.0"
        assert manifest["entry_point"] == "main"

    def test_skill_validation(self):
        registry = get_registry()
        registry.discover_skills()
        validation = registry.validate_skill("web_search")
        assert validation["valid"] is True, validation.get("issues")
        assert len(validation.get("issues", [])) == 0


class TestHtmlParsing:
    """Result extraction from DuckDuckGo HTML."""

    def test_parse_returns_ranked_results(self):
        results = web_search._parse_results(SAMPLE_HTML, 10)
        assert len(results) == 3
        assert results[0]["title"] == "Example A"
        assert results[0]["url"] == "https://example.com/a"
        assert results[0]["snippet"] == "This is snippet A about markets."

    def test_redirect_url_unwrapped(self):
        results = web_search._parse_results(SAMPLE_HTML, 10)
        assert results[1]["url"] == "https://example.com/b"

    def test_max_results_limited(self):
        results = web_search._parse_results(SAMPLE_HTML, 1)
        assert len(results) == 1

    def test_clean_html_strips_tags(self):
        results = web_search._parse_results(SAMPLE_HTML, 10)
        for r in results:
            assert "<" not in r["title"]
            assert "<" not in r["snippet"]


class TestMainEntryPoint:
    """main() behavior with mocked network."""

    def test_missing_query(self):
        result = web_search.main(query="")
        assert result["ok"] is False
        assert "query" in result["error"]

    def test_returns_results(self, monkeypatch):
        monkeypatch.setattr(
            web_search,
            "_fetch_html",
            lambda q, t: SAMPLE_HTML,
        )
        result = web_search.main(query="NSE RELIANCE stock", max_results=5)
        assert result["ok"] is True
        assert result["query"] == "NSE RELIANCE stock"
        assert result["count"] == 3
        assert len(result["results"]) == 3
        assert result["results"][0]["title"] == "Example A"

    def test_network_failure(self, monkeypatch):
        monkeypatch.setattr(
            web_search,
            "_fetch_html",
            lambda q, t: (_ for _ in ()).throw(Exception("DNS failure")),
        )
        result = web_search.main(query="anything")
        assert result["ok"] is False
        assert "Web search failed" in result["error"]


if __name__ == "__main__":
    import pytest as _pytest

    _sys.exit(_pytest.main([__file__, "-v"]))
