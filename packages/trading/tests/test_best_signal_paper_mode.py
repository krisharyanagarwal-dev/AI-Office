"""Tests for the bot's paper-mode wiring: venue, accounting and fleet state.

The bot's state file is read by the office fleet probes, so it must carry the
fleet's paper-boundary fields in the fleet's own lowercase convention while the
report and the paper targets keep the uppercase ``PAPER`` label.

Hand-derived numbers used below (notional 10,000 at price 100, rate 0.0001):

  * fee per leg                 = 100 * 100 * 0.0005 = 5.00
  * fees to open a carry        = 2 legs * 5.00 = 10.00
  * venue cash to build         = 10,000 * (1 + 0.10) * 1.01 = 11,110.00
  * cash after opening a carry  = 11,110 - 10,000 - 5 + 10,000 - 5 = 11,100.00
  * funding for one print       = 0.0001 * 10,000 = 1.00
  * cash after the open print   = 11,100 + 1.00 = 11,101.00
  * day P&L after the open      = 1.00 - 10.00 = -9.00
"""
import json

import pandas as pd

from best_signal.position import RiskLimits
from best_signal.runner import BotConfig, run_bot

EIGHT_HOURS_MS = 8 * 3_600_000
START_MS = 1_500_000_000_000
PRICE = 100.0


def write_funding(data_dir, symbol, rates, start_ms=START_MS):
    data_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "fundingTime": [
                start_ms + index * EIGHT_HOURS_MS for index in range(len(rates))
            ],
            "fundingRate": rates,
        }
    )
    frame.to_parquet(data_dir / f"{symbol}_funding.parquet")


def write_prices(data_dir, symbol, count, price=PRICE, start_ms=START_MS):
    data_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "open_time": [start_ms + index * EIGHT_HOURS_MS for index in range(count)],
            "open": [price] * count,
            "high": [price] * count,
            "low": [price] * count,
            "close": [price] * count,
            "volume": [1.0] * count,
        }
    )
    frame.to_parquet(data_dir / f"{symbol}_15m.parquet")


def make_data(data_dir, symbol="BTCUSDT", count=81, rate=0.0001):
    write_funding(data_dir, symbol, [rate] * count)
    write_prices(data_dir, symbol, count)


def make_config(tmp_path, **overrides):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    settings = {
        "symbols": ("BTCUSDT",),
        "data_dir": data_dir,
        "out_dir": out_dir,
        "state_path": tmp_path / "state.json",
        "equity": 10_000.0,
        "limits": RiskLimits(),
        "validate": False,
    }
    settings.update(overrides)
    return BotConfig(**settings)


def read_state(result) -> dict:
    return json.loads(result["paths"]["state"].read_text())


class TestFleetPaperBoundary:
    def test_the_state_file_carries_the_fleet_paper_boundary_fields(self, tmp_path):
        """Catches: a state file the office fleet probe cannot read."""
        config = make_config(tmp_path)
        make_data(config.data_dir)

        state = read_state(run_bot(config))

        assert state["mode"] == "paper"
        assert state["execution_enabled"] is False
        assert state["live_trading"] is False
        assert state["live"] is False
        assert state["status"] == "ok"
        assert state["last_run"]
        assert isinstance(state["positions"], list)
        assert isinstance(state["closed"], list)
        assert isinstance(state["realized_pnl"], (int, float))
        assert state["price"] == PRICE

    def test_the_report_marks_the_run_as_paper_and_the_venue_as_paper_trading(
        self, tmp_path
    ):
        """Catches: a report that reads like a live mandate."""
        config = make_config(tmp_path)
        make_data(config.data_dir)

        result = run_bot(config)
        report = json.loads(result["paths"]["json"].read_text())

        assert report["mode"] == "PAPER"
        assert report["live"] is False
        assert report["venue"]["paper_trading"] is True
        assert report["venue"]["live"] is False


class TestVenueAccounting:
    def test_the_run_opens_the_spot_and_perp_legs_on_the_paper_venue(self, tmp_path):
        """Catches: a paper target that never becomes a position anywhere."""
        config = make_config(tmp_path)
        make_data(config.data_dir)

        state = read_state(run_bot(config))
        venue = state["venue"]

        assert venue["positions"]["BTCUSDT"]["quantity"] == 100.0
        assert venue["positions"]["BTCUSDT_PERP"]["quantity"] == -100.0
        assert venue["margin_used"]["BTCUSDT_PERP"] == 1_000.0
        assert venue["fees_total"] == 10.0

    def test_funding_and_fees_land_in_the_day_pnl(self, tmp_path):
        """Catches: a book that books fees but never books the funding it earns."""
        config = make_config(tmp_path)
        make_data(config.data_dir)

        state = read_state(run_bot(config))

        assert state["day"]["funding"] == 1.0
        assert state["day"]["fees"] == 10.0
        assert state["day"]["pnl"] == -9.0
        assert state["venue"]["cash"] == 11_101.0

    def test_a_second_run_holds_the_carry_and_accrues_only_the_new_print(
        self, tmp_path
    ):
        """Catches: a runner that re-charges the entry fee on every run."""
        config = make_config(tmp_path)
        make_data(config.data_dir, count=81)
        run_bot(config)

        make_data(config.data_dir, count=82)
        state = read_state(run_bot(config))

        assert state["symbols"]["BTCUSDT"]["last_action"] == "HOLD"
        assert state["day"]["funding"] == 2.0
        assert state["day"]["fees"] == 10.0
        assert state["day"]["pnl"] == -8.0
        assert state["venue"]["cash"] == 11_102.0


class TestRiskStops:
    def test_a_measured_daily_loss_stops_new_entries_but_keeps_the_carry(
        self, tmp_path
    ):
        """Catches: a stand-down that liquidates the carry it was meant to protect."""
        config = make_config(tmp_path, limits=RiskLimits(max_daily_loss_pct=0.0001))
        make_data(config.data_dir, count=81)
        run_bot(config)

        make_data(config.data_dir, count=82)
        result = run_bot(config)
        state = read_state(result)

        position = result["positions"][0]
        assert position.action == "NO_TRADE"
        assert position.reason == "daily_loss_limit"
        assert state["symbols"]["BTCUSDT"]["side"] == 1
        assert state["venue"]["positions"]["BTCUSDT"]["quantity"] == 100.0
        assert state["venue"]["positions"]["BTCUSDT_PERP"]["quantity"] == -100.0
        assert state["day"]["pnl"] == -8.0

    def test_the_day_counters_reset_when_the_utc_date_changes(self, tmp_path):
        """Catches: yesterday's loss standing the book down forever."""
        config = make_config(tmp_path)
        make_data(config.data_dir, count=81)
        run_bot(config)

        state_path = config.state_path
        payload = json.loads(state_path.read_text())
        payload["day"] = {
            "date": "2020-01-01",
            "funding": 1.0,
            "fees": 10.0,
            "pnl": -9.0,
        }
        state_path.write_text(json.dumps(payload))

        make_data(config.data_dir, count=82)
        state = read_state(run_bot(config))

        assert state["day"]["date"] != "2020-01-01"
        assert state["day"]["funding"] == 1.0
        assert state["day"]["fees"] == 0.0
        assert state["day"]["pnl"] == 1.0
