"""Tests for paper-mode execution telemetry (JSONL sink, no live venue)."""

import json
from pathlib import Path

import pytest

from best_signal.execution import (
    ACTION_OPEN,
    ExecutionResult,
)
from best_signal.telemetry import CycleMetrics, TelemetrySink, record_cycle
from best_signal.fill_journal import FillJournal, FillRecord, record_fill


class _FakeRealism:
    slippage_bps = 10.0
    latency_ms = 5.0


class _FakeBroker:
    realism = _FakeRealism()
    paper_trading = True
    name = "paper"


def _result(filled: bool = True, partial: bool = False, fees: float = 1.0) -> ExecutionResult:
    return ExecutionResult(
        symbol="BTCUSDT",
        action=ACTION_OPEN,
        legs=(),
        fees=fees,
        filled=filled,
        reason="filled",
        partial=partial,
    )


class TestTelemetrySink:
    def test_records_one_jsonl_line_per_cycle(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        sink = TelemetrySink(path, enabled=True)
        metrics = CycleMetrics(
            cycle_ts="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            action="OPEN",
            side=1,
            notional=10000.0,
            slippage_bps=10.0,
            latency_ms=5.0,
            partial_fill=False,
            filled=True,
            filled_qty=100.0,
            fill_price=100.10,
            fees=5.005,
            reason="filled",
        )
        sink.record(metrics)
        sink.record(metrics)

        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            payload = json.loads(line)
            assert payload["symbol"] == "BTCUSDT"
            assert payload["action"] == "OPEN"
            assert payload["slippage_bps"] == 10.0
            assert payload["latency_ms"] == 5.0
            assert payload["fees"] == 5.005

    def test_disabled_sink_writes_nothing(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        sink = TelemetrySink(path, enabled=False)
        metrics = CycleMetrics(
            cycle_ts="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            action="OPEN",
            side=1,
            notional=10000.0,
            slippage_bps=0.0,
            latency_ms=0.0,
            partial_fill=False,
            filled=True,
            filled_qty=0.0,
            fill_price=None,
            fees=0.0,
            reason="held",
        )
        sink.record(metrics)
        assert not path.exists()

    def test_cycle_metrics_captures_actual_slippage_and_timeline(self, tmp_path):
        """CycleMetrics records measured slippage and fill timeline."""
        path = tmp_path / "telemetry.jsonl"
        sink = TelemetrySink(path, enabled=True)
        journal = FillJournal(tmp_path / "fills.jsonl", enabled=True)

        # Create mock fill and order with actual execution data
        class MockFill:
            order_id = "ord123"
            symbol = "BTCUSDT"
            side = "buy"
            quantity = 100.0
            price = 100.10
            commission = 5.005
            # Actual execution data
            spread_bps = 2.0
            bid = 99.99
            ask = 100.01
            fill_fraction = 1.0
            leg_sequence = 0
            venue_latency_ms = 3.0
            partial_fill = False

        class MockOrder:
            client_order_id = "ord123"
            symbol = "BTCUSDT"
            side = "buy"
            price = 100.0  # mid price at order time

        class MockRealism:
            slippage_bps = 10.0
            latency_ms = 5.0

        class MockBroker:
            realism = MockRealism()
            fill_journal = journal

        # Pre-record a fill in the journal
        fill = MockFill()
        order = MockOrder()
        broker = MockBroker()
        record_fill(journal, fill, order, broker)

        result = ExecutionResult(
            symbol="BTCUSDT", action="OPEN", legs=(), fees=10.0,
            filled=True, reason="filled", partial=False
        )

        record_cycle(
            sink=sink,
            symbol="BTCUSDT",
            side=1,
            notional=10000.0,
            action="OPEN",
            result=result,
            broker=broker,
        )

        # Verify actual measured slippage recorded
        payload = json.loads(path.read_text().strip())
        assert "actual_slippage_bps" in payload
        assert payload["actual_slippage_bps"] == pytest.approx(10.0)  # (100.10-100)/100*10000
        assert "bid_ask_spread_bps" in payload
        assert payload["bid_ask_spread_bps"] == 2.0
        assert "fill_timeline" in payload
        assert len(payload["fill_timeline"]) >= 1


class TestRecordCycle:
    def test_record_cycle_pulls_realism_from_broker(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        sink = TelemetrySink(path, enabled=True)
        broker = _FakeBroker()
        result = _result(fees=10.0)

        record_cycle(
            sink,
            "BTCUSDT",
            1,
            10000.0,
            ACTION_OPEN,
            result,
            broker,
        )

        payload = json.loads(path.read_text().strip())
        assert payload["symbol"] == "BTCUSDT"
        assert payload["action"] == "OPEN"
        assert payload["side"] == 1
        assert payload["notional"] == 10000.0
        assert payload["slippage_bps"] == 10.0
        assert payload["latency_ms"] == 5.0
        assert payload["partial_fill"] is False
        assert payload["filled"] is True
        assert payload["filled_qty"] == 0.0
        assert payload["fill_price"] is None
        assert payload["fees"] == 10.0
        assert payload["reason"] == "filled"

    def test_record_cycle_partial_fill_flag(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        sink = TelemetrySink(path, enabled=True)
        broker = _FakeBroker()
        result = _result(filled=False, partial=True, fees=2.5)

        record_cycle(
            sink,
            "ETHUSDT",
            -1,
            5000.0,
            "CLOSE",
            result,
            broker,
        )

        payload = json.loads(path.read_text().strip())
        assert payload["partial_fill"] is True
        assert payload["filled"] is False
        assert payload["fees"] == 2.5
