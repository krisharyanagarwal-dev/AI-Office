"""Dost skill: keyless news sentiment per symbol.

Wraps the `web_search` skill to fetch public news headlines/snippets for a
symbol and scores sentiment from the returned text. Read-only — no API keys,
no credentials, nothing posted or ordered.

Returns per-symbol sentiment: {"symbol", "score", "signal", "reason", "sources"}
where score is in [-1, 1] (negative to positive) and signal is
"negative" | "positive" | "neutral". A "negative" signal is what the screener
manipulation watch treats as a risk factor (see news_sentiment_enabled gate).

Follows the dost skill registry pattern (SKILL_MANIFEST) so
dost/skills/registry.py can discover and register it.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dost/  (for `skills.web_search`)

from skills.web_search import main as _web_search


NEWS_SENTIMENT_NEUTRAL_BAND = 0.2  # |score| below this is "neutral"
NEWS_SENTIMENT_DEFAULT_MAX_RESULTS = 5

POSITIVE_WORDS = frozenset({
    "beat", "beats", "beating",
    "rally", "rallies", "rallying",
    "surge", "surges", "surging",
    "jump", "jumps", "jumping",
    "gain", "gains", "gaining",
    "rise", "rises", "rising",
    "boost", "boosts", "boosting",
    "record",
    "profit", "profits", "profitable",
    "upgrade", "upgrades", "upgraded",
    "outperform",
    "strong",
    "raise", "raises", "raising", "raised",
    "buy",
})

NEGATIVE_WORDS = frozenset({
    "miss", "misses", "missing",
    "plunge", "plunges", "plunging",
    "crash", "crashes", "crashing",
    "slump", "slumps", "slumping",
    "fall", "falls", "falling",
    "drop", "drops", "dropping",
    "decline", "declines", "declining",
    "cut", "cuts", "cutting",
    "downgrade", "downgrades", "downgraded",
    "underperform",
    "weak", "weakness",
    "loss", "losses",
    "warn", "warns", "warning",
    "investigation",
    "fraud",
    "lawsuit",
    "probe",
    "sell",
})


@dataclass
class NewsSentimentConfig:
    max_results: int = NEWS_SENTIMENT_DEFAULT_MAX_RESULTS
    timeout: int = 10


SKILL_MANIFEST = {
    "name": "news_sentiment",
    "version": "1.0.0",
    "description": "Keyless news sentiment per symbol, wrapping the web_search skill",
    "author": "dost",
    "dependencies": ["web_search"],
    "entry_point": "main",
    "module_file": "news_sentiment.py",
    "test_file": "test_news_sentiment.py",
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
    "tags": ["screener", "news", "sentiment"],
    "enabled": True,
}

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z%&.+-]*")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _score_text(text: str) -> tuple[int, int, int]:
    """Return (positive_hits, negative_hits, total_hits) for sentiment words in text."""
    tokens = _tokenize(text)
    positives = sum(1 for t in tokens if t in POSITIVE_WORDS)
    negatives = sum(1 for t in tokens if t in NEGATIVE_WORDS)
    return positives, negatives, positives + negatives


class NewsSentiment:
    """Scores news sentiment for a symbol via the keyless web_search skill."""

    def __init__(self, config: NewsSentimentConfig | None = None):
        self.config = config or NewsSentimentConfig()
        self._cache: dict[str, dict[str, Any]] = {}

    def get_news_sentiment(self, symbol: str) -> dict[str, Any]:
        """Sentiment for one symbol. Degrades to neutral on any failure."""
        key = str(symbol).strip().upper()
        if key in self._cache:
            return dict(self._cache[key])

        result: dict[str, Any] = {
            "symbol": key,
            "score": 0.0,
            "signal": "neutral",
            "reason": "no news found",
            "sources": 0,
        }
        try:
            search = _web_search(query=f"{key} stock news", max_results=self.config.max_results, timeout=self.config.timeout)
        except Exception:
            result["reason"] = "web search unavailable"
            self._cache[key] = result
            return result

        if not isinstance(search, dict) or not search.get("ok"):
            result["reason"] = f"web search failed: {search.get('error') if isinstance(search, dict) else 'unknown'}"
            self._cache[key] = result
            return result

        results = search.get("results") or []
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

        band = NEWS_SENTIMENT_NEUTRAL_BAND
        if sources == 0:
            signal = "neutral"
            reason = "no news found"
        elif score <= -band:
            signal = "negative"
            reason = f"{negatives} negative vs {positives} positive signals across {sources} items"
        elif score >= band:
            signal = "positive"
            reason = f"{positives} positive vs {negatives} negative signals across {sources} items"
        else:
            signal = "neutral"
            reason = f"mixed/weak signal ({positives} positive, {negatives} negative across {sources} items)"

        result = {
            "symbol": key,
            "score": round(score, 4),
            "signal": signal,
            "reason": reason,
            "sources": sources,
        }
        self._cache[key] = result
        return result

    def is_negative_news(self, symbol: str) -> bool:
        """True when the symbol's latest news sentiment is negative."""
        return self.get_news_sentiment(symbol)["signal"] == "negative"


# Default process-wide instance used by module-level convenience functions.
NEWS_SENTIMENT = NewsSentiment()


def get_news_sentiment(symbol: str) -> dict[str, Any]:
    return NEWS_SENTIMENT.get_news_sentiment(symbol)


def is_negative_news(symbol: str) -> bool:
    return NEWS_SENTIMENT.is_negative_news(symbol)


def main(symbol: str, max_results: int | None = None, timeout: int | None = None) -> dict[str, Any]:
    """Registry entry point: sentiment for one symbol."""
    skill = NewsSentiment()
    if max_results is not None:
        skill.config.max_results = int(max_results)
    if timeout is not None:
        skill.config.timeout = int(timeout)
    return skill.get_news_sentiment(symbol)


if __name__ == "__main__":
    import json

    print(json.dumps(main("RELIANCE.NS"), indent=2))
