"""Dost skill: keyless social sentiment per symbol (Reddit/WSB).

Wraps the `web_search` skill to fetch Reddit posts/comments mentioning a
symbol and scores sentiment from the returned text. Read-only — no API keys,
no credentials, nothing posted or ordered.

Returns per-symbol sentiment: {"symbol", "score", "signal", "reason", "sources"}
where score is in [-1, 1] (negative to positive) and signal is
"negative" | "positive" | "neutral". A "negative" signal is what the screener
manipulation watch treats as a risk factor (see social_sentiment_enabled gate).

Follows the dost skill registry pattern (SKILL_MANIFEST) so
dost/skills/registry.py can discover and register it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `skills.*`)

from skills.news_sentiment import (  # reuse scoring helpers & neutral band
    NEWS_SENTIMENT_NEUTRAL_BAND,
    _score_text,
)
from skills.web_search import main as _web_search


SOCIAL_SENTIMENT_DEFAULT_MAX_RESULTS = 5


@dataclass
class SocialSentimentConfig:
    max_results: int = SOCIAL_SENTIMENT_DEFAULT_MAX_RESULTS
    timeout: int = 10


SKILL_MANIFEST = {
    "name": "social_sentiment",
    "version": "1.0.0",
    "description": "Keyless social sentiment per symbol (Reddit), wrapping the web_search skill",
    "author": "dost",
    "dependencies": ["web_search", "news_sentiment"],
    "entry_point": "main",
    "module_file": "social_sentiment.py",
    "test_file": "test_social_sentiment.py",
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
    "tags": ["screener", "social", "sentiment", "reddit"],
    "enabled": True,
}

SOCIAL_SENTIMENT_NEUTRAL_BAND = NEWS_SENTIMENT_NEUTRAL_BAND
SOCIAL_SENTIMENT_DEFAULT_MAX_RESULTS = 5


class SocialSentiment:
    """Scores social sentiment for a symbol via Reddit results from web_search."""

    def __init__(self, config: SocialSentimentConfig | None = None):
        self.config = config or SocialSentimentConfig()
        self._cache: dict[str, dict[str, Any]] = {}

    def get_social_sentiment(self, symbol: str) -> dict[str, Any]:
        """Sentiment for one symbol. Degrades to neutral on any failure."""
        key = str(symbol).strip().upper()
        if key in self._cache:
            return dict(self._cache[key])

        result: dict[str, Any] = {
            "symbol": key,
            "score": 0.0,
            "signal": "neutral",
            "reason": "no social posts found",
            "sources": 0,
        }
        try:
            search = _web_search(
                query=f"{key} site:reddit.com stock",
                max_results=self.config.max_results,
                timeout=self.config.timeout,
            )
        except Exception:
            result["reason"] = "web search unavailable"
            self._cache[key] = result
            return result

        if not isinstance(search, dict) or not search.get("ok"):
            result["reason"] = (
                f"web search failed: {search.get('error') if isinstance(search, dict) else 'unknown'}"
            )
            self._cache[key] = result
            return result

        results = search.get("results") or []
        sources = len(results)
        if sources == 0:
            result = {
                "symbol": key,
                "score": 0.0,
                "signal": "neutral",
                "reason": "no social posts found",
                "sources": 0,
            }
            self._cache[key] = result
            return result

        positives = negatives = total = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            text = str(item.get("title", "") or "") + " " + str(item.get("snippet", "") or "")
            p, n, t = _score_text(text)
            positives += p
            negatives += n
            total += t

        sources = len(results)
        if total > 0:
            score = (positives - negatives) / total
        else:
            score = 0.0
        score = max(-1.0, min(1.0, score))

        band = SOCIAL_SENTIMENT_NEUTRAL_BAND
        if score <= -band:
            signal = "negative"
            reason = f"{negatives} negative vs {positives} positive social signals across {sources} items"
        elif score >= band:
            signal = "positive"
            reason = f"{positives} positive vs {negatives} negative social signals across {sources} items"
        else:
            signal = "neutral"
            reason = f"mixed/weak social signal ({positives} positive, {negatives} negative across {sources} items)"

        result = {
            "symbol": key,
            "score": round(score, 4),
            "signal": signal,
            "reason": reason,
            "sources": sources,
        }
        self._cache[key] = result
        return result

    def is_negative_social(self, symbol: str) -> bool:
        """True when the symbol's latest social sentiment is negative."""
        return self.get_social_sentiment(symbol)["signal"] == "negative"


# Default process-wide instance used by module-level convenience functions.
SOCIAL_SENTIMENT = SocialSentiment()


def get_social_sentiment(symbol: str) -> dict[str, Any]:
    return SOCIAL_SENTIMENT.get_social_sentiment(symbol)


def is_negative_social(symbol: str) -> bool:
    return SOCIAL_SENTIMENT.is_negative_social(symbol)


def main(symbol: str, max_results: int | None = None, timeout: int | None = None) -> dict[str, Any]:
    """Registry entry point: social sentiment for one symbol."""
    skill = SocialSentiment()
    if max_results is not None:
        skill.config.max_results = int(max_results)
    if timeout is not None:
        skill.config.timeout = int(timeout)
    return skill.get_social_sentiment(symbol)


if __name__ == "__main__":
    import json

    print(json.dumps(main("RELIANCE.NS"), indent=2))
