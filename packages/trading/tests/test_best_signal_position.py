"""Tests for the paper-only position emitter.

The emitter is the last gate before a position exists. It may only ever
describe a paper target: no exchange, no credential, no live order. Every
risk cap and the kill switch have to turn into an explicit NO_TRADE rather
than a silently resized position.
"""
import numpy as np
import pandas as pd
import pytest

from best_signal.evidence import CARRY_OOS_AUDIT, CandidateRecord, Citation
from best_signal.funding import FundingPrint
from best_signal.position import RiskLimits, build_paper_position
from best_signal.rules import RuleDecision, RuleState

ACCEPTED_RECORD = CandidateRecord(
    name="always_on_carry",
    thesis="t",
    kind="structural",
    status="ACCEPTED",
    reasons=(),
    citations=(Citation(CARRY_OOS_AUDIT, "archived control book"),),
    rule_key="always_on_carry",
)

NO_TRADE_RECORDS = [
    CandidateRecord(
        name="research_only",
        thesis="t",
        kind="timing",
        status="RESEARCH",
        reasons=(),
        citations=(Citation(CARRY_OOS_AUDIT, "archived control book"),),
        rule_key="always_on_carry",
    )
]


class FlatRule:
    """Test-only rule that always stands down."""

    name = "flat_rule"

    def new_state(self):
        return RuleState(side=0)

    def step(self, prints, state, returns=None):
        return RuleDecision(side=0, reason="stand_down")


def make_prints(rates, start_ms=0, step_ms=8 * 3600 * 1000):
    return [
        FundingPrint(ts_ms=start_ms + index * step_ms, rate=rate)
        for index, rate in enumerate(rates)
    ]


class TestPaperOnly:
    def test_position_is_never_live(self):
        position = build_paper_position(
            "BTCUSDT", make_prints([0.0001] * 3), [ACCEPTED_RECORD], RiskLimits()
        )
        assert position.mode == "PAPER"
        assert position.live is False

    def test_serialized_position_carries_no_order_payload(self):
        position = build_paper_position(
            "BTCUSDT", make_prints([0.0001] * 3), [ACCEPTED_RECORD], RiskLimits()
        )
        payload = position.to_dict()
        assert payload["mode"] == "PAPER"
        assert payload["live"] is False
        assert set(payload) == {
            "symbol",
            "action",
            "side",
            "notional",
            "reason",
            "candidate",
            "mode",
            "live",
        }


class TestKillSwitch:
    def test_no_tradable_candidate_stands_down(self):
        position = build_paper_position(
            "BTCUSDT", make_prints([0.0001] * 3), NO_TRADE_RECORDS, RiskLimits()
        )
        assert position.action == "NO_TRADE"
        assert position.side == 0
        assert position.notional == 0.0

    def test_kill_switch_stands_down(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(kill_switch=True),
        )
        assert position.action == "NO_TRADE"
        assert "kill_switch" in position.reason

    def test_daily_loss_limit_stands_down(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(max_daily_loss_pct=0.03),
            daily_loss_pct=-0.05,
        )
        assert position.action == "NO_TRADE"
        assert "daily_loss" in position.reason

    def test_empty_history_stands_down(self):
        position = build_paper_position(
            "BTCUSDT", [], [ACCEPTED_RECORD], RiskLimits()
        )
        assert position.action == "NO_TRADE"
        assert "no_history" in position.reason


class TestSizing:
    def test_accepted_candidate_opens_the_carry_side(self):
        position = build_paper_position(
            "BTCUSDT", make_prints([0.0001] * 3), [ACCEPTED_RECORD], RiskLimits()
        )
        assert position.action == "OPEN"
        assert position.side == 1
        assert position.notional == pytest.approx(10_000.0)
        assert position.candidate == "always_on_carry"

    def test_symbol_notional_cap_limits_size(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(max_symbol_notional=2_500.0),
        )
        assert position.notional == pytest.approx(2_500.0)

    def test_equity_weight_limits_size(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(max_position_weight=0.5),
            equity=20_000.0,
        )
        assert position.notional == pytest.approx(10_000.0)

    def test_gross_notional_cap_limits_size(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(max_gross_notional=10_000.0),
            gross_notional=9_000.0,
        )
        assert position.notional == pytest.approx(1_000.0)

    def test_exhausted_gross_notional_stands_down(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(max_gross_notional=10_000.0),
            gross_notional=10_000.0,
        )
        assert position.action == "NO_TRADE"
        assert position.notional == 0.0

    def test_max_symbols_blocks_a_new_position(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(max_symbols=2),
            open_symbols=2,
        )
        assert position.action == "NO_TRADE"
        assert "max_symbols" in position.reason


class TestActions:
    def test_unchanged_side_holds(self):
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(),
            current_side=1,
            current_notional=10_000.0,
        )
        assert position.action == "HOLD"
        assert position.side == 1
        assert position.notional == pytest.approx(10_000.0)

    def test_flat_decision_closes_an_open_position(self):
        record = CandidateRecord(
            name="flat_candidate",
            thesis="t",
            kind="structural",
            status="ACCEPTED",
            reasons=(),
            citations=(Citation(CARRY_OOS_AUDIT, "archived control book"),),
            rule_key="flat_test",
        )
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [record],
            RiskLimits(),
            current_side=1,
            current_notional=10_000.0,
            rules={"flat_test": FlatRule},
        )
        assert position.action == "CLOSE"
        assert position.side == 0
        assert position.notional == 0.0

    def test_side_is_always_within_the_allowed_range(self):
        position = build_paper_position(
            "BTCUSDT", make_prints([-0.0001] * 3), [ACCEPTED_RECORD], RiskLimits()
        )
        assert position.side in (-1, 0, 1)


class TestRegimeAwarePosition:
    def test_volatile_returns_stand_down_always_on_carry(self):
        rule_returns = pd.Series(np.random.default_rng(7).normal(0.0, 0.05, 150))
        position = build_paper_position(
            "BTCUSDT",
            make_prints([0.0001] * 3),
            [ACCEPTED_RECORD],
            RiskLimits(),
            returns=rule_returns,
        )
        assert position.action == "NO_TRADE"
        assert position.side == 0
        assert position.reason == "volatile_regime_stand_down"

    def test_none_returns_collects_funding_backward_compatible(self):
        position = build_paper_position(
            "BTCUSDT", make_prints([0.0001] * 3), [ACCEPTED_RECORD], RiskLimits()
        )
        assert position.action == "OPEN"
        assert position.side == 1
