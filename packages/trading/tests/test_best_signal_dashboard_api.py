"""Tests for the best-signal dashboard API (FastAPI server)."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from best_signal.dashboard_api import create_app


class TestDashboardAPI:
    @pytest.fixture
    def client(self, tmp_path):
        # Create test report files
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # Use recent timestamps (within last hour)
        now = datetime.now(timezone.utc)
        ts1 = (now - timedelta(minutes=30)).isoformat()
        ts2 = (now - timedelta(minutes=10)).isoformat()

        # Create fills.jsonl
        fills_data = [
            {
                "ts": ts1,
                "symbol": "BTCUSDT",
                "market": "spot",
                "side": "buy",
                "quantity": 100.0,
                "price": 100.10,
                "mid_price": 100.0,
                "fees": 5.005,
                "slippage_bps": 10.0,
                "latency_ms": 5.0,
                "partial_fill": False,
                "order_id": "abc123",
                "venue": "paper",
                "mode": "PAPER",
                "spread_bps": 2.0,
                "bid": 99.99,
                "ask": 100.01,
                "fill_fraction": 1.0,
                "leg_sequence": 0,
                "venue_latency_ms": 3.0,
            },
            {
                "ts": ts2,
                "symbol": "ETHUSDT",
                "market": "spot",
                "side": "sell",
                "quantity": 50.0,
                "price": 2000.0,
                "mid_price": 2001.0,
                "fees": 10.0,
                "slippage_bps": 5.0,
                "latency_ms": 3.0,
                "partial_fill": True,
                "order_id": "def456",
                "venue": "paper",
                "mode": "PAPER",
                "spread_bps": 1.5,
                "bid": 1999.5,
                "ask": 2000.5,
                "fill_fraction": 0.8,
                "leg_sequence": 1,
                "venue_latency_ms": 2.0,
            },
        ]
        (reports_dir / "fills.jsonl").write_text("\n".join(json.dumps(f) for f in fills_data) + "\n")

        # Create telemetry.jsonl
        telemetry_data = [
            {
                "cycle_ts": ts1,
                "symbol": "BTCUSDT",
                "action": "OPEN",
                "side": 1,
                "notional": 10000.0,
                "slippage_bps": 10.0,
                "latency_ms": 5.0,
                "partial_fill": False,
                "filled": True,
                "filled_qty": 100.0,
                "fill_price": 100.10,
                "fees": 5.005,
                "reason": "filled",
                "actual_slippage_bps": 10.0,
                "bid_ask_spread_bps": 2.0,
                "fill_timeline": [],
            },
            {
                "cycle_ts": ts2,
                "symbol": "ETHUSDT",
                "action": "CLOSE",
                "side": -1,
                "notional": 5000.0,
                "slippage_bps": 5.0,
                "latency_ms": 3.0,
                "partial_fill": True,
                "filled": False,
                "filled_qty": 40.0,
                "fill_price": 2000.0,
                "fees": 10.0,
                "reason": "partial",
                "actual_slippage_bps": 5.0,
                "bid_ask_spread_bps": 1.5,
                "fill_timeline": [],
            },
        ]
        (reports_dir / "telemetry.jsonl").write_text("\n".join(json.dumps(t) for t in telemetry_data) + "\n")

        # Create execution_summary.json
        summary_data = {
            "period": "2026-01-01T00:00:00+00:00/2026-01-01T02:00:00+00:00",
            "start_ts": 1704067200000,
            "end_ts": 1704074400000,
            "total_fills": 2,
            "total_volume": 110010.0,
            "avg_slippage_bps": 7.5,
            "slippage_p50_bps": 7.5,
            "slippage_p95_bps": 10.0,
            "avg_latency_ms": 4.0,
            "partial_fill_rate": 0.5,
            "total_fees": 15.005,
            "fees_vs_slippage_bps": 1.36,
            "by_symbol": {
                "BTCUSDT": {
                    "fills": 1,
                    "volume": 10010.0,
                    "avg_slippage_bps": 10.0,
                    "slippage_p50_bps": 10.0,
                    "slippage_p95_bps": 10.0,
                    "avg_latency_ms": 5.0,
                    "avg_venue_latency_ms": 3.0,
                    "partial_fill_rate": 0.0,
                    "total_fees": 5.005,
                },
                "ETHUSDT": {
                    "fills": 1,
                    "volume": 100000.0,
                    "avg_slippage_bps": 5.0,
                    "slippage_p50_bps": 5.0,
                    "slippage_p95_bps": 5.0,
                    "avg_latency_ms": 3.0,
                    "avg_venue_latency_ms": 2.0,
                    "partial_fill_rate": 1.0,
                    "total_fees": 10.0,
                },
            },
        }
        (reports_dir / "execution_summary.json").write_text(json.dumps(summary_data, indent=2) + "\n")

        # Create best_signal_report.json
        report_data = {
            "generated_at": "2026-01-01T02:00:00+00:00",
            "mode": "PAPER",
            "live": False,
            "selected_candidate": None,
            "ranking": [],
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "action": "OPEN",
                    "side": 1,
                    "notional": 10010.0,
                    "reason": "funding_carry",
                    "candidate": "always_on_carry",
                    "live": False,
                }
            ],
            "validation": {},
            "reconciliation": None,
            "caveats": ["Paper mode only", "No live execution"],
            "data_summary": {},
            "signals": [],
        }
        (reports_dir / "best_signal_report.json").write_text(json.dumps(report_data, indent=2) + "\n")

        return TestClient(create_app(reports_dir))

    def test_fills_endpoint(self, client):
        response = client.get("/api/execution/fills?symbol=BTCUSDT&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            fill = data[0]
            assert "symbol" in fill
            assert "side" in fill
            assert "price" in fill
            assert "slippage_bps" in fill

    def test_fills_endpoint_all_symbols(self, client):
        response = client.get("/api/execution/fills?limit=100")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_fills_endpoint_pagination(self, client):
        response = client.get("/api/execution/fills?limit=1&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        response = client.get("/api/execution/fills?limit=1&offset=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    def test_telemetry_endpoint(self, client):
        response = client.get("/api/execution/telemetry?symbol=BTCUSDT&hours=24")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_telemetry_endpoint_all_symbols(self, client):
        response = client.get("/api/execution/telemetry?hours=24")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_summary_endpoint(self, client):
        response = client.get("/api/execution/summary?period=daily")
        assert response.status_code == 200
        data = response.json()
        assert "total_fills" in data
        assert "avg_slippage_bps" in data
        assert data["total_fills"] == 2
        assert data["avg_slippage_bps"] == 7.5

    def test_summary_endpoint_invalid_period(self, client):
        response = client.get("/api/execution/summary?period=invalid")
        assert response.status_code == 422  # Validation error

    def test_report_endpoint(self, client):
        response = client.get("/api/report/latest")
        assert response.status_code == 200
        data = response.json()
        assert "positions" in data
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "BTCUSDT"

    def test_report_endpoint_not_found(self, tmp_path):
        reports_dir = tmp_path / "empty_reports"
        reports_dir.mkdir(parents=True)
        client = TestClient(create_app(reports_dir))
        response = client.get("/api/report/latest")
        assert response.status_code == 404

    def test_summary_endpoint_not_found(self, tmp_path):
        reports_dir = tmp_path / "empty_reports"
        reports_dir.mkdir(parents=True)
        client = TestClient(create_app(reports_dir))
        response = client.get("/api/execution/summary?period=daily")
        assert response.status_code == 404