"""Tests for the best-signal report writer.

The report is the artifact a human reads to judge what the bot did and why.
It has to carry the evidence ranking, the paper positions, the validation
verdicts and the caveats, and it must never look like a live mandate.
"""
import json
from datetime import datetime, timezone

from best_signal.evidence import default_registry, select_tradable
from best_signal.position import PaperPosition
from best_signal.report import build_report, render_markdown, write_report
from best_signal.runner import ExecutionSummary


def make_position(action="OPEN", side=1, notional=10_000.0):
    return PaperPosition(
        symbol="BTCUSDT",
        action=action,
        side=side,
        notional=notional,
        reason="always_collect",
        candidate="always_on_carry",
    )


class TestReport:
    def test_report_is_paper_only(self):
        report = build_report(default_registry(), [make_position()])
        assert report["mode"] == "PAPER"
        assert report["live"] is False

    def test_report_records_the_selected_candidate(self):
        report = build_report(default_registry(), [make_position()])
        assert report["selected_candidate"]["name"] == "always_on_carry"
        assert report["selected_candidate"]["thesis"]

    def test_report_has_no_trade_when_nothing_is_tradable(self):
        report = build_report([], [make_position(action="NO_TRADE", side=0, notional=0.0)])
        assert report["selected_candidate"] is None
        assert "NO_TRADE" in render_markdown(report)

    def test_report_lists_positions(self):
        report = build_report(default_registry(), [make_position()])
        assert report["positions"][0]["symbol"] == "BTCUSDT"
        assert report["positions"][0]["action"] == "OPEN"
        assert report["positions"][0]["live"] is False

    def test_report_carries_the_ranking(self):
        report = build_report(default_registry(), [make_position()])
        assert report["ranking"][0]["rank"] == 1
        assert report["ranking"][0]["name"] == "always_on_carry"

    def test_report_carries_the_validation_verdicts(self):
        report = build_report(
            default_registry(),
            [make_position()],
            validations={
                "BTCUSDT": {
                    "verdict": "VALIDATED OUT-OF-SAMPLE",
                    "frozen": {"out_of_sample": {"net": 350.30}},
                    "failed_checks": [],
                    "caveats": ["delta-flat (long spot + short perp), not delta-zero"],
                }
            },
        )
        assert report["validation"]["BTCUSDT"]["verdict"] == "VALIDATED OUT-OF-SAMPLE"
        assert "VALIDATED OUT-OF-SAMPLE" in render_markdown(report)

    def test_report_is_json_serializable(self):
        report = build_report(default_registry(), [make_position()])
        assert json.loads(json.dumps(report))["mode"] == "PAPER"

    def test_report_trims_the_raw_print_dump(self):
        report = build_report(
            default_registry(),
            [],
            validations={
                "BTCUSDT": {
                    "verdict": "VALIDATED OUT-OF-SAMPLE",
                    "frozen": {
                        "out_of_sample": {
                            "net": 350.30,
                            "prints": [{"ts_ms": 1, "rate": 0.1}],
                            "side_series": [1, 1],
                        }
                    },
                }
            },
        )
        frozen = report["validation"]["BTCUSDT"]["frozen"]["out_of_sample"]
        assert "prints" not in frozen
        assert "side_series" not in frozen
        assert frozen["prints_count"] == 1


class TestMarkdown:
    def test_markdown_names_the_winner_first(self):
        markdown = render_markdown(build_report(default_registry(), [make_position()]))
        assert markdown.index("always_on_carry") < markdown.index("persistence_flip_carry")

    def test_markdown_carries_the_caveats(self):
        markdown = render_markdown(build_report(default_registry(), [make_position()]))
        assert "delta-flat" in markdown

    def test_markdown_marks_the_report_as_paper(self):
        markdown = render_markdown(build_report(default_registry(), [make_position()]))
        assert "PAPER" in markdown


class TestWrite:
    def test_write_report_creates_json_and_markdown(self, tmp_path):
        report = build_report(default_registry(), [make_position()])
        paths = write_report(report, tmp_path)
        assert paths["json"].exists()
        assert paths["markdown"].exists()
        assert json.loads(paths["json"].read_text())["mode"] == "PAPER"
        assert paths["markdown"].read_text().startswith("# Best-signal bot report")

    def test_write_report_uses_stable_file_names(self, tmp_path):
        paths = write_report(build_report(default_registry(), [make_position()]), tmp_path)
        assert paths["json"].name == "best_signal_report.json"
        assert paths["markdown"].name == "best_signal_report.md"


class TestExecutionQuality:
    def test_report_includes_execution_quality_section(self, tmp_path):
        """Report includes execution quality section with slippage/latency/fees."""
        summary = ExecutionSummary(
            period="daily",
            start_ts=1704067200000,
            end_ts=1704153600000,
            total_fills=10,
            total_volume=100_000.0,
            avg_slippage_bps=2.5,
            slippage_p50_bps=2.0,
            slippage_p95_bps=5.0,
            avg_latency_ms=3.5,
            partial_fill_rate=0.0,
            total_fees=50.0,
            fees_vs_slippage_bps=1.2,
            by_symbol={
                "BTCUSDT": {"fills": 6, "avg_slippage_bps": 2.0, "avg_latency_ms": 3.0, "fees": 30.0},
                "ETHUSDT": {"fills": 4, "avg_slippage_bps": 3.0, "avg_latency_ms": 4.0, "fees": 20.0},
            }
        )
        
        report = build_report(
            records=[], positions=[], validations={}, data_summary={},
            reconciliation={}, venue={}, signals=[], execution_summary=summary
        )
        
        # Check execution quality section exists in JSON
        assert "execution_quality" in report
        eq = report["execution_quality"]
        assert eq["total_fills"] == 10
        assert eq["avg_slippage_bps"] == 2.5
        
        # Check execution quality section exists in markdown
        markdown = render_markdown(report)
        assert "## Execution Quality" in markdown
        assert "Avg Slippage (bps)" in markdown
        assert "2.5" in markdown
        assert "P50 Slippage" in markdown
        assert "Avg Latency (ms)" in markdown
