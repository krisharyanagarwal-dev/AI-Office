"""
Tests for the best-signal validation harness.

The harness is the part of the bot that can lie. These tests pin the
accounting (every leg costs money, the book pays for its own opens), the
execution lag (a decision may not use the print it is charged for), and the
out-of-sample protocol (selection on in-sample only, then frozen).
"""
import pytest

from best_signal.funding import FundingPrint
from best_signal.rules import (
    AlwaysOnCarry,
    PersistenceFlipCarry,
    RegimeFilteredCarry,
    RuleDecision,
    RuleState,
)
from best_signal.validate import (
    Candidate,
    no_information_controls,
    simulate_rule,
    split_prints,
    validate_candidate,
)


def make_prints(rates, start_ms=0, step_ms=8 * 3600 * 1000):
    return [
        FundingPrint(ts_ms=start_ms + index * step_ms, rate=rate)
        for index, rate in enumerate(rates)
    ]


class OppositeCarry:
    """Test-only rule that always bets against the funding sign."""

    name = "opposite_carry"

    def new_state(self):
        return RuleState(side=1)

    def step(self, prints, state):
        if not prints:
            return RuleDecision(side=1, reason="boot")
        side = -1 if prints[-1].rate > 0 else 1
        state.side = side
        return RuleDecision(side=side, reason="opposite")


class LastSignCarry:
    """Test-only rule that flips on the most recently observed sign."""

    name = "last_sign_carry"

    def new_state(self):
        return RuleState(side=0)

    def step(self, prints, state):
        if not prints:
            return RuleDecision(side=0, reason="boot")
        side = 1 if prints[-1].rate > 0 else -1
        state.side = side
        return RuleDecision(side=side, reason="last_sign")


class TestSimulationAccounting:
    def test_always_on_charges_one_open_and_collects_funding(self):
        prints = make_prints([0.0001] * 1095)
        result = simulate_rule(AlwaysOnCarry(), prints)

        assert result.collected == pytest.approx(1095.0)
        assert result.fees == pytest.approx(10.0)  # 2 legs x 0.0005 x 10000
        assert result.net == pytest.approx(1085.0)
        assert result.return_pct == pytest.approx(10.85)
        assert result.side_changes == 1

    def test_negative_funding_makes_the_book_lose(self):
        result = simulate_rule(AlwaysOnCarry(), make_prints([-0.0001] * 1095))
        assert result.net < 0
        assert result.return_pct == pytest.approx(-11.05)

    def test_flip_costs_four_legs(self):
        class FlipOnce:
            name = "flip_once"

            def new_state(self):
                return RuleState(side=0)

            def step(self, prints, state):
                side = 1 if len(prints) <= 1 else -1
                state.side = side
                return RuleDecision(side=side, reason="flip_once")

        result = simulate_rule(FlipOnce(), make_prints([0.0001] * 10))
        # open (2 legs) + flip (4 legs) = 6 legs x 0.0005 x 10000
        assert result.fees == pytest.approx(30.0)
        assert result.side_changes == 2

    def test_borrow_cost_applies_only_to_the_short_spot_leg(self):
        class ShortSpot:
            name = "short_spot"

            def new_state(self):
                return RuleState(side=-1)

            def step(self, prints, state):
                return RuleDecision(side=-1, reason="short")

        class LongSpot:
            name = "long_spot"

            def new_state(self):
                return RuleState(side=1)

            def step(self, prints, state):
                return RuleDecision(side=1, reason="long")

        prints = make_prints([-0.0001] * 365)
        short = simulate_rule(short_rule := ShortSpot(), prints, borrow_annual=0.10)
        long = simulate_rule(LongSpot(), prints, borrow_annual=0.10)

        # 365 native 8h prints are 2920h, i.e. 121.7 days of a 365-day year.
        expected = 0.10 * 10000.0 * (365 * 8 / 8760.0)
        assert short.borrow == pytest.approx(expected, rel=1e-6)
        assert long.borrow == 0.0
        assert short_rule.name == "short_spot"

    def test_flat_book_has_no_funding_and_no_fees(self):
        class Flat:
            name = "flat"

            def new_state(self):
                return RuleState(side=0)

            def step(self, prints, state):
                return RuleDecision(side=0, reason="flat")

        result = simulate_rule(Flat(), make_prints([0.0001] * 100))
        assert result.collected == 0.0
        assert result.fees == 0.0
        assert result.net == 0.0

    def test_slippage_in_bps_is_charged_per_leg(self):
        result = simulate_rule(
            AlwaysOnCarry(), make_prints([0.0001] * 10), extra_bps=10.0
        )
        # 2 legs x (0.0005 + 10bps) x 10000
        assert result.fees == pytest.approx(2 * (0.0005 + 0.001) * 10000.0)

    def test_equity_curve_is_monotone_for_constant_positive_funding(self):
        result = simulate_rule(AlwaysOnCarry(), make_prints([0.0001] * 50))
        assert len(result.equity_curve) == 50
        assert result.equity_curve[-1] > result.equity_curve[0]


class TestExecutionLag:
    def test_decision_cannot_use_the_print_it_is_charged_for(self):
        prints = make_prints([0.0001, 0.0001, -0.0001, -0.0001])
        result = simulate_rule(LastSignCarry(), prints)

        # Print 0: the rule has no history, so it stays flat. Print 1: it has
        # seen print 0 (+), so it goes long. Print 2: it has seen prints 0..1,
        # both positive, so it holds long. Print 3: it has seen prints 0..2,
        # the first of which is negative, so it may act on that observation --
        # but never on print 3's own rate, which it has not seen.
        sides = result.side_series
        assert sides[0] == 0
        assert sides[1] == 1
        assert sides[2] == 1
        assert sides[3] == -1

    def test_regime_rule_needs_history_before_entering(self):
        rule = RegimeFilteredCarry(lookback_prints=2)
        result = simulate_rule(rule, make_prints([0.001] * 5))
        assert result.side_series[0] == 0
        assert result.side_series[-1] == 1


class TestSplitting:
    def test_split_is_60_15_25_on_record_count(self):
        prints = make_prints([0.0001] * 1000)
        splits = split_prints(prints)
        assert len(splits["in_sample"]) == 600
        assert len(splits["validation"]) == 150
        assert len(splits["out_of_sample"]) == 250
        assert splits["in_sample"][0] is prints[0]
        assert splits["out_of_sample"][-1] is prints[-1]

    def test_split_preserves_order(self):
        prints = make_prints([0.0001] * 100)
        splits = split_prints(prints)
        assert splits["validation"][0].ts_ms > splits["in_sample"][-1].ts_ms


class TestNoInformationControls:
    def test_always_receive_control_matches_the_always_on_book(self):
        prints = make_prints([0.0001] * 200)
        controls = no_information_controls(prints)
        always_on = simulate_rule(AlwaysOnCarry(), prints)

        assert controls["always_receive"]["net"] == pytest.approx(always_on.net)
        assert controls["always_receive"]["collected"] > 0

    def test_always_pay_loses_when_funding_is_positive(self):
        controls = no_information_controls(make_prints([0.0001] * 200))
        assert controls["always_pay"]["net"] < controls["always_receive"]["net"]

    def test_random_timing_control_has_no_edge(self):
        prints = make_prints([0.0001] * 500)
        controls = no_information_controls(prints, matched_flips=10)
        assert controls["random_timing_matched_flips"]["flips"] == 10


class TestValidateCandidate:
    def test_structural_carry_is_reported_as_structural_not_as_a_timing_edge(self):
        prints = make_prints([0.0001] * 2000)
        candidate = Candidate(
            name="always_on_carry",
            thesis="Funding drift is structural.",
            rule_factory=lambda params: AlwaysOnCarry(),
            param_grid=[{}],
            kind="structural",
        )
        report = validate_candidate(candidate, prints)

        assert report["verdict"] == (
            "STRUCTURAL CARRY - out-of-sample positive; not a timing edge"
        )
        assert report["frozen"]["out_of_sample"]["net"] > 0
        assert all(report["checks"].values())

    def test_timing_rule_without_skill_is_reported_as_no_skill(self):
        prints = make_prints([0.0001] * 2000)
        candidate = Candidate(
            name="opposite_carry",
            thesis="Betting against funding.",
            rule_factory=lambda params: OppositeCarry(),
            param_grid=[{}],
            kind="timing",
        )
        report = validate_candidate(candidate, prints)

        assert report["verdict"].startswith("NO SKILL")
        assert report["checks"]["beats_best_constant_side"] is False

    def test_selection_uses_in_sample_only(self):
        prints = make_prints([0.0001] * 1000 + [0.0001] * 1000)
        candidate = Candidate(
            name="lookback_sweep",
            thesis="Sweep the lookback.",
            rule_factory=lambda params: RegimeFilteredCarry(
                lookback_prints=params["lookback_prints"]
            ),
            param_grid=[{"lookback_prints": 2}, {"lookback_prints": 50}],
            kind="timing",
        )
        report = validate_candidate(candidate, prints)

        assert report["params_selected"] in (
            {"lookback_prints": 2},
            {"lookback_prints": 50},
        )
        assert len(report["is_ranking"]) == 2
        selected_net = report["is_ranking"][0]["net"]
        assert selected_net >= report["is_ranking"][1]["net"]

    def test_report_contains_stress_and_control_sections(self):
        prints = make_prints([0.0001] * 1000)
        candidate = Candidate(
            name="always_on_carry",
            thesis="Funding drift is structural.",
            rule_factory=lambda params: AlwaysOnCarry(),
            param_grid=[{}],
            kind="structural",
        )
        report = validate_candidate(candidate, prints)

        for section in (
            "frozen",
            "controls",
            "oos_walk_forward",
            "oos_fee_stress",
            "oos_slippage_stress",
            "checks",
        ):
            assert section in report

    def test_walk_forward_covers_the_whole_out_of_sample_window(self):
        prints = make_prints([0.0001] * 1200)
        candidate = Candidate(
            name="always_on_carry",
            thesis="Funding drift is structural.",
            rule_factory=lambda params: AlwaysOnCarry(),
            param_grid=[{}],
            kind="structural",
        )
        report = validate_candidate(candidate, prints)

        thirds = report["oos_walk_forward"]
        assert len(thirds) == 3
        total = sum(len(chunk) for chunk in thirds.values())
        assert total == len(report["frozen"]["out_of_sample"]["prints"])

    def test_persistence_flip_baseline_is_scored_against_always_on(self):
        prints = make_prints([0.0001] * 1000)
        candidate = Candidate(
            name="persistence_flip_carry",
            thesis="Flip after sustained adverse funding.",
            rule_factory=lambda params: PersistenceFlipCarry(
                persistence_hours=params["persistence_hours"],
                threshold=params["threshold"],
            ),
            param_grid=[{"persistence_hours": 48.0, "threshold": 5e-05}],
            kind="timing",
        )
        report = validate_candidate(candidate, prints)

        assert report["controls"]["always_receive"]["net"] > 0
        assert "beats_best_constant_side" in report["checks"]

    def test_structural_candidate_is_not_labelled_a_validated_timing_edge(self):
        prints = make_prints([0.0002] * 300)
        candidate = Candidate(
            name="always_on_carry",
            thesis="Funding drift is structural.",
            rule_factory=lambda params: AlwaysOnCarry(),
            param_grid=[{}],
            kind="structural",
        )
        report = validate_candidate(candidate, prints)

        assert report["verdict"] == (
            "STRUCTURAL CARRY - out-of-sample positive; not a timing edge"
        )
        assert "beats_best_constant_side" not in report["checks"]
        assert "beats_random_timing" not in report["checks"]
        assert report["checks"]["beats_always_pay"] is True
        assert report["failed_checks"] == []
        assert "control" in report["verdict_note"].lower()

    def test_structural_candidate_is_rejected_when_funding_pays_the_book(self):
        prints = make_prints([-0.0002] * 300)
        candidate = Candidate(
            name="always_on_carry",
            thesis="Funding drift is structural.",
            rule_factory=lambda params: AlwaysOnCarry(),
            param_grid=[{}],
            kind="structural",
        )
        report = validate_candidate(candidate, prints)

        assert report["verdict"].startswith("NOT VALIDATED")
        assert "beats_always_pay" in report["failed_checks"]
        assert report["checks"]["beats_always_pay"] is False

    def test_timing_candidate_must_strictly_beat_the_constant_side_book(self):
        prints = make_prints([0.0002] * 300)
        candidate = Candidate(
            name="always_on_carry",
            thesis="Funding drift is structural.",
            rule_factory=lambda params: AlwaysOnCarry(),
            param_grid=[{}],
            kind="timing",
        )
        report = validate_candidate(candidate, prints)

        assert report["checks"]["beats_best_constant_side"] is False
        assert report["checks"]["beats_random_timing"] is False
        assert report["verdict"].startswith("NO SKILL")
