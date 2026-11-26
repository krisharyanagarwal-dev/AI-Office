"""Tests for paper-mode fill journal (JSONL sink, no live venue)."""

import json
from pathlib import Path
import pytest

from best_signal.fill_journal import FillRecord, FillJournal, record_fill


class TestFillRecord:
    def test_fill_record_serializes_to_json(self):
        rec = FillRecord(
            ts="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            market="spot",
            side="buy",
            quantity=100.0,
            price=100.10,
            mid_price=100.0,
            fees=5.005,
            slippage_bps=10.0,
            latency_ms=5.0,
            partial_fill=False,
            order_id="abc123",
        )
        data = rec.to_dict()
        assert data["symbol"] == "BTCUSDT"
        assert data["side"] == "buy"
        assert data["slippage_bps"] == 10.0
        assert data["partial_fill"] is False
        # Round-trip
        rec2 = FillRecord(**data)
        assert rec2.symbol == "BTCUSDT"


class TestFillJournal:
    def test_records_one_jsonl_line_per_fill(self, tmp_path):
        path = tmp_path / "fills.jsonl"
        journal = FillJournal(path, enabled=True)

        rec = FillRecord(
            ts="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            market="spot",
            side="buy",
            quantity=100.0,
            price=100.10,
            mid_price=100.0,
            fees=5.005,
            slippage_bps=10.0,
            latency_ms=5.0,
            partial_fill=False,
            order_id="abc123",
        )
        journal.record(rec)
        journal.record(rec)

        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            payload = json.loads(line)
            assert payload["symbol"] == "BTCUSDT"
            assert payload["side"] == "buy"
            assert payload["slippage_bps"] == 10.0

    def test_disabled_journal_writes_nothing(self, tmp_path):
        path = tmp_path / "fills.jsonl"
        journal = FillJournal(path, enabled=False)

        rec = FillRecord(
            ts="2026-01-01T00:00:00+00:00",
            symbol="BTCUSDT",
            market="spot",
            side="buy",
            quantity=100.0,
            price=100.10,
            mid_price=100.0,
            fees=5.005,
            slippage_bps=0.0,
            latency_ms=0.0,
            partial_fill=False,
            order_id="abc123",
        )
        journal.record(rec)
        assert not path.exists()


class TestRecordFillHelper:
    def test_record_fill_creates_record_from_fill_order_broker(self, tmp_path):
        """record_fill helper extracts all fields from Fill, Order, and broker realism."""
        path = tmp_path / "fills.jsonl"
        journal = FillJournal(path, enabled=True)

        # Mock fill, order, broker with realism
        class MockFill:
            client_order_id = "ord123"
            symbol = "BTCUSDT"
            side = "buy"  # Fill.side is string in our code
            quantity = 100.0
            price = 100.10
            commission = 5.005

        class MockOrder:
            client_order_id = "ord123"
            symbol = "BTCUSDT"
            side = "buy"
            price = 100.0

        class MockRealism:
            slippage_bps = 10.0
            latency_ms = 5.0

        class MockBroker:
            realism = MockRealism()

        fill = MockFill()
        order = MockOrder()
        broker = MockBroker()

        record_fill(journal, fill, order, broker)

        payload = json.loads(path.read_text().strip())
        assert payload["symbol"] == "BTCUSDT"
        assert payload["side"] == "buy"
        assert payload["quantity"] == 100.0
        assert payload["price"] == 100.10
        assert payload["mid_price"] == 100.0  # order.price
        assert payload["fees"] == 5.005
        assert payload["slippage_bps"] == 10.0
        assert payload["latency_ms"] == 5.0
        assert payload["partial_fill"] is False
        assert payload["order_id"] == "ord123"
        assert payload["venue"] == "paper"
        assert payload["mode"] == "PAPER"