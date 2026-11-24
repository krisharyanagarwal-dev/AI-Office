"""Tests for the best-signal bot's signal emission.

The bot sends a signal whenever it finds a difference between the action it
emits for a symbol and standing pat: an OPEN, a CLOSE, or a FLIP changes the
book, so it is a signal worth sending. Holding (HOLD) or standing down
(NO_TRADE) with no change to the book is not a signal. Signals are written to
a dedicated artifact and carried in the report so a human or a downstream
consumer can read exactly what the bot found and when.
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
            "fundingTime": [start_ms + index * EIGHT_HOURS_MS for index in range(len(rates))],
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


class TestSignalEmission:
    def test_emits_a_signal_when_the_action_differs_from_standing_pat(self, tmp_path):
        """Catches: an OPEN that changes the book must be sent as a signal."""
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        signals = json.loads(result["paths"]["signals"].read_text())
        assert len(signals) == 1
        signal = signals[0]
        assert signal["symbol"] == "BTCUSDT"
        assert signal["action"] == "OPEN"
        assert signal["side"] == 1
        assert signal["notional"] > 0

    def test_emits_no_signal_when_the_book_is_unchanged(self, tmp_path):
        """Catches: a HOLD that keeps the carry is not a signal to send."""
        config = make_config(tmp_path)
        make_data(config.data_dir)
        run_bot(config)  # opens the carry
        make_data(config.data_dir, count=82)
        result = run_bot(config)  # holds, book unchanged
        signals = json.loads(result["paths"]["signals"].read_text())
        assert signals == []

    def test_writes_a_dedicated_signals_artifact(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        assert result["paths"]["signals"].exists()
        assert result["paths"]["signals"].name == "best_signal_signals.json"

    def test_signals_are_carried_in_the_report(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        report = json.loads(result["paths"]["json"].read_text())
        assert report["signals"]
        assert report["signals"][0]["action"] == "OPEN"
        assert report["signals"][0]["symbol"] == "BTCUSDT"

    def test_signal_carries_price_and_timestamp(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        signal = json.loads(result["paths"]["signals"].read_text())[0]
        assert signal["price"] == PRICE
        assert signal["generated_at"]

    def test_render_markdown_lists_the_signals(self, tmp_path):
        from best_signal.report import render_markdown, build_report
        from best_signal.evidence import default_registry
        from best_signal.position import PaperPosition

        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        report = result["report"]
        markdown = render_markdown(report)
        assert "## Signals" in markdown
        assert "OPEN" in markdown
