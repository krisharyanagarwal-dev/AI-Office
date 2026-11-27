"""Dost skill: keyless public web search.

Uses DuckDuckGo's public HTML endpoint (no API key, no credentials). Read-only
public data only — nothing is posted, modified, or ordered.

Returns ranked results: [{title, url, snippet}] so the LLM can narrate from
real snippets instead of inventing facts.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass
class SkillConfig:
    """Configuration for web_search skill."""
    max_results: int = 5
    timeout: int = 10


SKILL_MANIFEST = {
    "name": "web_search",
    "version": "1.0.0",
    "description": "Keyless public web search via DuckDuckGo HTML endpoint",
    "author": "dost",
    "dependencies": [],
    "entry_point": "main",
    "module_file": "web_search.py",
    "test_file": "test_web_search.py",
    "config_schema": {
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            "timeout": {"type": "integer", "minimum": 5, "maximum": 60},
        },
    },
    "default_config": {
        "max_results": 5,
        "timeout": 10,
    },
    "tags": ["search", "web", "research"],
    "enabled": True,
}

DUCKDUCKGO_HTML = "https://duckduckgo.com/html/"


def _fetch_html(query: str, timeout: int) -> str:
    """Fetch DuckDuckGo HTML results for a query. Raises on failure."""
    encoded = urllib.parse.urlencode({"q": query})
    url = DUCKDUCKGO_HTML + "?" + encoded
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            ),
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", errors="replace")
    # Detect CAPTCHA/challenge page served to bot requests
    if "anomaly-modal" in html or "bots use DuckDuckGo too" in html:
        raise ValueError("CAPTCHA page served - bot detection triggered")
    return html


def _parse_results(html: str, max_results: int) -> list[dict]:
    """Parse result links and snippets from DuckDuckGo HTML."""
    results: list[dict] = []

    # Each result block looks like:
    # <a rel="nofollow" class="result__a" href="...">Title</a>
    # ... <a class="result__snippet" ...>snippet</a>  or a <span class="result__snippet">
    link_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_re = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_span_re = re.compile(
        r'<span[^>]+class="result__snippet"[^>]*>(.*?)</span>',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_re.findall(html)
    snippets = snippet_re.findall(html)
    if not snippets:
        snippets = snippet_span_re.findall(html)

    def _clean(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    for i, (href, title) in enumerate(links):
        if i >= max_results:
            break
        title = _clean(title)
        url = href
        # DuckDuckGo wraps URLs in a redirect; extract the actual target.
        if url.startswith("//duckduckgo.com/l/?"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if qs.get("uddg"):
                url = qs["uddg"][0]
        snippet = ""
        if i < len(snippets):
            snippet = _clean(snippets[i])
        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
        })

    return results


def main(config: Optional[SkillConfig] = None, **kwargs) -> dict:
    """Search the public web.

    Args:
        config: Skill configuration
        **kwargs: query (str), max_results (int), timeout (int)

    Returns:
        {"ok": True, "results": [...]} or {"ok": False, "error": "..."}
    """
    if config is None:
        config = SkillConfig()

    query = kwargs.get("query", "")
    if not query or not str(query).strip():
        return {"ok": False, "error": "Missing required argument: query"}

    max_results = int(kwargs.get("max_results", config.max_results))
    timeout = int(kwargs.get("timeout", config.timeout))

    try:
        html = _fetch_html(str(query).strip(), timeout)
    except ValueError as e:
        # CAPTCHA page served - bot detection triggered; return empty results
        return {"ok": False, "error": f"Bot detection: {e}", "results": [], "count": 0}
    except Exception as e:
        return {"ok": False, "error": f"Web search failed: {e}"}

    results = _parse_results(html, max_results)
    return {
        "ok": True,
        "query": str(query).strip(),
        "results": results,
        "count": len(results),
    }


if __name__ == "__main__":
    import json
    import sys

    result = main(query="RELIANCE.NS stock price", max_results=3)
    print(json.dumps(result, indent=2))
