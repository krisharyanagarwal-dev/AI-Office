"""Tests for the social_sentiment skill.

Covers sentiment scoring from web_search results, negative/positive/neutral
signals, graceful degradation when web_search fails, per-symbol caching, and
the main entry point. No network — web_search is monkeypatched.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from skills.social_sentiment import (
    SOCIAL_SENTIMENT,
    SocialSentiment,
    get_social_sentiment,
    is_negative_social,
    main,
)


@pytest.fixture(autouse=True)
def _clear_social_cache():
    SOCIAL_SENTIMENT._cache.clear()


def _search(results, ok=True, error=None):
    def fake(query="", max_results=5, timeout=10, config=None):
        return {"ok": ok, "query": query, "results": results, "count": len(results), "error": error}
    return fake


POSITIVE_RESULTS = [
    {"title": "RELIANCE mooning on WSB", "snippet": "RELIANCE stock rally continues, shares surge on strong earnings beat."},
    {"title": "Buy RELIANCE call options", "snippet": "WallStreetBets is bullish on RELIANCE, huge gains expected."},
]

NEGATIVE_RESULTS = [
    {"title": "RELIANCE dumping hard", "snippet": "RELIANCE crash and plunge trigger downgrade and massive losses."},
    {"title": "RELIANCE fraud probe on Reddit", "snippet": "Investigation and lawsuit fears push RELIANCE shares lower."},
]

MIXED_RESULTS = [
    {"title": "RELIANCE in line with estimates", "snippet": "Earnings came in as expected, shares flat."},
]


# ----------------------- scoring -----------------------

def test_positive_social_scores_positive(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search(POSITIVE_RESULTS))
    sentiment = get_social_sentiment("RELIANCE.NS")

    assert sentiment["symbol"] == "RELIANCE.NS"
    assert sentiment["signal"] == "positive"
    assert sentiment["score"] > 0
    assert sentiment["sources"] == 2


def test_negative_social_scores_negative(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search(NEGATIVE_RESULTS))
    sentiment = get_social_sentiment("RELIANCE.NS")

    assert sentiment["signal"] == "negative"
    assert sentiment["score"] < 0
    assert is_negative_social("RELIANCE.NS") is True


def test_neutral_when_no_sentiment_words(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search(MIXED_RESULTS))
    sentiment = get_social_sentiment("RELIANCE.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["score"] == 0.0


def test_score_clamps_to_minus_one(monkeypatch):
    """Many negative hits must clamp score at -1.0, never beyond."""
    many_negative = [dict(NEGATIVE_RESULTS[0]) for _ in range(20)]
    monkeypatch.setattr("skills.social_sentiment._web_search", _search(many_negative))
    sentiment = get_social_sentiment("RELIANCE.NS")

    assert sentiment["signal"] == "negative"
    assert sentiment["score"] == -1.0


# ----------------------- graceful degradation -----------------------

def test_web_search_exception_degrades_to_neutral(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("skills.social_sentiment._web_search", boom)
    sentiment = get_social_sentiment("DOWN.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["score"] == 0.0
    assert sentiment["sources"] == 0


def test_web_search_not_ok_degrades_to_neutral(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search([], ok=False, error="bot detection"))
    sentiment = get_social_sentiment("CAPTCHA.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["score"] == 0.0


def test_web_search_empty_results_neutral(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search([]))
    sentiment = get_social_sentiment("NOCOVERAGE.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["reason"] == "no social posts found"


# ----------------------- caching -----------------------

def test_get_social_sentiment_caches_repeat_symbols(monkeypatch):
    calls = SimpleNamespace(n=0)

    def counting(query="", max_results=5, timeout=10, config=None):
        calls.n += 1
        return _search(POSITIVE_RESULTS)(query, max_results, timeout, config)

    monkeypatch.setattr("skills.social_sentiment._web_search", counting)
    skill = SocialSentiment()

    skill.get_social_sentiment("BANK.NS")
    skill.get_social_sentiment("bank.ns")  # case-insensitive cache key
    assert calls.n == 1


# ----------------------- main entry point -----------------------

def test_main_entry_point_returns_sentiment_dict(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search(NEGATIVE_RESULTS))
    result = main("RELIANCE.NS")

    assert result["symbol"] == "RELIANCE.NS"
    assert result["signal"] == "negative"
    assert {"score", "signal", "reason", "sources"} <= set(result)


def test_main_entry_point_respects_max_results(monkeypatch):
    seen = {}

    def fake(query="", max_results=5, timeout=10, config=None):
        seen["max_results"] = max_results
        return _search([])(query, max_results, timeout, config)

    monkeypatch.setattr("skills.social_sentiment._web_search", fake)
    main("RELIANCE.NS", max_results=3)
    assert seen["max_results"] == 3


def test_is_negative_social_false_for_positive(monkeypatch):
    monkeypatch.setattr("skills.social_sentiment._web_search", _search(POSITIVE_RESULTS))
    assert is_negative_social("RELIANCE.NS") is False
