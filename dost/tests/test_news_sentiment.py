"""Tests for the news_sentiment skill.

Covers sentiment scoring from web_search results, negative/positive/neutral
signals, graceful degradation when web_search fails, per-symbol caching, and
the main entry point. No network — web_search is monkeypatched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from skills.news_sentiment import (
    NEWS_SENTIMENT,
    NEWS_SENTIMENT_NEUTRAL_BAND,
    NewsSentiment,
    get_news_sentiment,
    is_negative_news,
    main,
)


@pytest.fixture(autouse=True)
def _clear_sentiment_cache():
    """Isolate tests that share the module-level NEWS_SENTIMENT singleton cache."""
    NEWS_SENTIMENT._cache.clear()


def _search(results, ok=True, error=None):
    def fake(query="", max_results=5, timeout=10, config=None):
        return {"ok": ok, "query": query, "results": results, "count": len(results), "error": error}
    return fake


POSITIVE_RESULTS = [
    {"title": "RELIANCE beats profit estimates", "snippet": "Reliance reported record profit and raised guidance."},
    {"title": "Reliance stock rally continues", "snippet": "Shares rally on a strong earnings beat."},
]

NEGATIVE_RESULTS = [
    {"title": "RELIANCE misses estimates, profit slump", "snippet": "Profit miss and revenue cut trigger downgrade."},
    {"title": "Regulatory probe weighs on Reliance", "snippet": "Fraud investigation and lawsuit fears push shares lower."},
]

MIXED_RESULTS = [
    {"title": "RELIANCE in line with estimates", "snippet": "Earnings came in as expected, shares flat."},
]


# ----------------------- scoring -----------------------

def test_positive_news_scores_positive(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search(POSITIVE_RESULTS))
    sentiment = get_news_sentiment("RELIANCE.NS")

    assert sentiment["symbol"] == "RELIANCE.NS"
    assert sentiment["signal"] == "positive"
    assert sentiment["score"] > 0
    assert sentiment["sources"] == 2


def test_negative_news_scores_negative(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search(NEGATIVE_RESULTS))
    sentiment = get_news_sentiment("RELIANCE.NS")

    assert sentiment["signal"] == "negative"
    assert sentiment["score"] < 0
    assert is_negative_news("RELIANCE.NS") is True


def test_neutral_when_no_sentiment_words(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search(MIXED_RESULTS))
    sentiment = get_news_sentiment("RELIANCE.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["score"] == 0.0


def test_score_stays_within_minus_one_to_plus_one(monkeypatch):
    """Many negative hits must clamp score at -1.0, never beyond."""
    many_negative = [
        {
            "title": "RELIANCE crashes on fraud probe",
            "snippet": "Shares plunge as lawsuit deepens losses and cuts guidance.",
        }
        for _ in range(20)
    ]
    monkeypatch.setattr("skills.news_sentiment._web_search", _search(many_negative))
    sentiment = get_news_sentiment("RELIANCE.NS")

    assert sentiment["signal"] == "negative"
    assert sentiment["score"] == -1.0


def test_neutral_band_is_0_2():
    assert NEWS_SENTIMENT_NEUTRAL_BAND == 0.2


# ----------------------- graceful degradation -----------------------

def test_web_search_exception_degrades_to_neutral(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("skills.news_sentiment._web_search", boom)
    sentiment = get_news_sentiment("DOWN.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["score"] == 0.0
    assert sentiment["sources"] == 0


def test_web_search_not_ok_degrades_to_neutral(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search([], ok=False, error="bot detection"))
    sentiment = get_news_sentiment("CAPTCHA.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["score"] == 0.0


def test_web_search_empty_results_neutral(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search([]))
    sentiment = get_news_sentiment("NOCOVERAGE.NS")

    assert sentiment["signal"] == "neutral"
    assert sentiment["reason"] == "no news found"


# ----------------------- caching -----------------------

def test_get_news_sentiment_caches_repeat_symbols(monkeypatch):
    calls = SimpleNamespace(n=0)

    def counting(query="", max_results=5, timeout=10, config=None):
        calls.n += 1
        return _search(POSITIVE_RESULTS)(query, max_results, timeout, config)

    monkeypatch.setattr("skills.news_sentiment._web_search", counting)
    skill = NewsSentiment()

    skill.get_news_sentiment("BANK.NS")
    skill.get_news_sentiment("bank.ns")  # case-insensitive cache key
    assert calls.n == 1


# ----------------------- main entry point -----------------------

def test_main_entry_point_returns_sentiment_dict(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search(NEGATIVE_RESULTS))
    result = main("RELIANCE.NS")

    assert result["symbol"] == "RELIANCE.NS"
    assert result["signal"] == "negative"
    assert {"score", "signal", "reason", "sources"} <= set(result)


def test_main_entry_point_respects_max_results(monkeypatch):
    seen = {}

    def fake(query="", max_results=5, timeout=10, config=None):
        seen["max_results"] = max_results
        return _search([])(query, max_results, timeout, config)

    monkeypatch.setattr("skills.news_sentiment._web_search", fake)
    main("RELIANCE.NS", max_results=3)
    assert seen["max_results"] == 3


def test_is_negative_news_false_for_positive(monkeypatch):
    monkeypatch.setattr("skills.news_sentiment._web_search", _search(POSITIVE_RESULTS))
    assert is_negative_news("RELIANCE.NS") is False
