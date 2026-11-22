"""
Tests for the paper-book collector.

This is the first live evidence the trading departments have had: before it, seven
departments cited retired collectors and answered anyway. Two behaviours matter more
than the rest and are pinned here:

  * the PAPER boundary is checked before anything about performance, and a breach is
    URGENT no matter how healthy the rest of the book looks;
  * an empty book is NOT ok. A bot with zero closed trades has produced no sample, and
    reporting 0 P&L as fine is exactly how silence gets mistaken for success.
"""
import pytest

from core import sources

HEALTHY = {
    "status": "ok", "open_positions": 2, "closed_trades": 14, "realized_pnl": 31.4,
    "last_run": None, "mark_price": 61025.7, "mode": "paper",
    "execution_enabled": False, "live_trading": False, "multistrat_status": "ok",
    "poller_status": "ok", "history_rows": 120, "history_any_trade": True,
    "history_age_min": 3.0, "history_first_ts": "2026-11-18T22:03:28+00:00",
}


@pytest.fixture
def book(monkeypatch):
    def _set(**over):
        facts = dict(HEALTHY)
        facts.update(over)
        monkeypatch.setattr(sources, "_mini", lambda: {"paper_book": facts})
        return sources.paper_book()
    return _set


def test_healthy_book_is_ok(book):
    r = book()
    assert r["ok"], r["problems"]
    assert "closed 14" in r["summary"]


@pytest.mark.parametrize("breach", [
    {"execution_enabled": True},
    {"live_trading": True},
    {"mode": "live"},
])
def test_paper_boundary_breach_is_urgent(book, breach):
    """An otherwise perfect book must still fail on a breached boundary."""
    r = book(**breach)
    assert not r["ok"]
    assert r["problems"][0].startswith("URGENT"), r["problems"]


def test_zero_trades_is_not_ok(book):
    """The live case on 2026-11-22: 120 history rows, not one trade."""
    r = book(closed_trades=0, open_positions=0, realized_pnl=0.0, history_any_trade=False)
    assert not r["ok"]
    assert any("no sample" in p for p in r["problems"]), r["problems"]


def test_degraded_upstream_is_reported_with_its_reason(book):
    r = book(poller_status="degraded", poller_provider_error="no ALPHAINSIDER_API_KEY configured")
    assert not r["ok"]
    assert any("ALPHAINSIDER_API_KEY" in p for p in r["problems"])


def test_unreadable_state_is_not_an_empty_book(book):
    r = book(book_error="FileNotFoundError: no such file")
    assert not r["ok"]
    assert any("unreadable" in p for p in r["problems"])


def test_unreachable_mini_fails_closed(monkeypatch):
    monkeypatch.setattr(sources, "_mini", lambda: {"error": "ssh timed out"})
    r = sources.paper_book()
    assert not r["ok"] and "cannot verify" in r["summary"]


def test_missing_paper_block_fails_closed(monkeypatch):
    """The mini answered, but produced no book facts: unknown is not ok."""
    monkeypatch.setattr(sources, "_mini", lambda: {"jobs": {}})
    assert not sources.paper_book()["ok"]
