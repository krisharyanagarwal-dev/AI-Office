"""
_office_context() must not carry a stale round-up into a new round.

On 2026-11-21 the office had a 5-day-old summary in state, written under a
different department set, and fed it to every round as "Previous round-up (do
not repeat it, build on it)". It steered Michael's questions and the specialists'
answers: backtest-auditor replied as a blockchain security auditor about a
deadline long past. Summaries are stamped now, and an old or unstamped one is
dropped rather than trusted because it is the only thing in the field.
"""
import time
import types

from core.autopilot import Autopilot

FRESH = "FRESH-ROUNDUP-MARKER the specialists agreed on X"
STALE = "STALE-ROUNDUP-MARKER SEV-1 fleet blocks the 18:00 UTC deadline"


def _stub(state):
    """The smallest object _office_context() needs, so the real method runs."""
    return types.SimpleNamespace(
        hive=types.SimpleNamespace(list_tasks=lambda status=None: []),
        _org_digest=lambda: "Organisation state: office-hud: OK.",
        state=state,
        cfg={"interval_min": 30},
    )


def _context(state):
    return Autopilot._office_context(_stub(state))


def test_unstamped_summary_is_dropped():
    """What the live state actually held: a summary with no timestamp at all."""
    out = _context({"last_summary": STALE})
    assert "STALE-ROUNDUP-MARKER" not in out
    assert "Previous round-up" not in out


def test_summary_older_than_four_intervals_is_dropped():
    old = time.time() - 5 * 30 * 60      # 5 intervals at interval_min=30
    out = _context({"last_summary": STALE, "last_summary_at": old})
    assert "STALE-ROUNDUP-MARKER" not in out


def test_five_day_old_summary_is_dropped():
    out = _context({"last_summary": STALE, "last_summary_at": time.time() - 5 * 86400})
    assert "STALE-ROUNDUP-MARKER" not in out


def test_recent_summary_is_still_carried_forward():
    """The feature must survive the fix: one round should build on the last."""
    out = _context({"last_summary": FRESH, "last_summary_at": time.time() - 60})
    assert "FRESH-ROUNDUP-MARKER" in out
    assert "Previous round-up" in out


def test_no_summary_at_all_is_fine():
    out = _context({})
    assert "Previous round-up" not in out
    assert "Organisation state" in out, "the rest of the context must still be built"
