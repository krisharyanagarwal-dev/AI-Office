"""Tests for the one-command best-signal bot runner.

The runner is what a human (or a scheduler) invokes: it loads the evidence
registry, loads funding history, emits paper targets, runs the out-of-sample
validation and writes every artifact. It must never place an order.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from best_signal.execution import approve_target, risk_limits_for
from best_signal.position import PaperPosition, RiskLimits
from best_signal.runner import (
    BotConfig,
    STATE_FILENAME,
    main,
    run_bot,
    _apply_position,
    _restore_governor_book,
)
from risk import RiskGovernor

EIGHT_HOURS_MS = 8 * 3_600_000
FIFTEEN_MIN_MS = 15 * 60 * 1000
START_MS = 1_500_000_000_000
EQUITY = 10_000.0


def write_funding(data_dir, symbol, rates, start_ms=START_MS):
    data_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "fundingTime": [start_ms + index * EIGHT_HOURS_MS for index in range(len(rates))],
            "fundingRate": rates,
        }
    )
    frame.to_parquet(data_dir / f"{symbol}_funding.parquet")


def make_data(data_dir, symbols=("BTCUSDT",), rate=0.0001, count=80):
    for symbol in symbols:
        write_funding(data_dir, symbol, [rate] * count)


def write_prices(data_dir, symbol, n_bars, start_ms=START_MS, vol=0.05, drift=0.0, seed=1):
    """Write 15m close bars whose close-to-close returns match ``vol``/``drift``."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, n_bars)
    closes = 100.0 * np.exp(np.cumsum(returns))
    frame = pd.DataFrame(
        {
            "open_time": [start_ms + index * FIFTEEN_MIN_MS for index in range(n_bars)],
            "close": closes,
        }
    )
    frame.to_parquet(data_dir / f"{symbol}_15m.parquet")


def make_config(tmp_path, **overrides):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    settings = {
        "symbols": ("BTCUSDT",),
        "data_dir": data_dir,
        "out_dir": out_dir,
        "equity": 10_000.0,
        "limits": RiskLimits(),
        "validate": False,
    }
    settings.update(overrides)
    return BotConfig(**settings)


class TestRunBot:
    def test_run_bot_opens_a_paper_position(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        position = result["positions"][0]
        assert position.action == "OPEN"
        assert position.side == 1
        assert position.mode == "PAPER"
        assert position.live is False

    def test_run_bot_holds_the_position_on_the_next_run(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        run_bot(config)
        second = run_bot(config)
        assert second["positions"][0].action == "HOLD"
        assert second["positions"][0].side == 1

    def test_run_bot_persists_the_state_file(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        state = json.loads(result["paths"]["state"].read_text())
        assert state["symbols"]["BTCUSDT"]["side"] == 1

    def test_run_bot_writes_the_report_artifacts(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir)
        result = run_bot(config)
        assert result["paths"]["json"].exists()
        assert result["paths"]["markdown"].exists()
        assert json.loads(result["paths"]["json"].read_text())["mode"] == "PAPER"
        assert result["paths"]["markdown"].read_text().startswith(
            "# Best-signal bot report"
        )

    def test_run_bot_honours_the_kill_switch(self, tmp_path):
        config = make_config(tmp_path, limits=RiskLimits(kill_switch=True))
        make_data(config.data_dir)
        result = run_bot(config)
        position = result["positions"][0]
        assert position.action == "NO_TRADE"
        assert position.reason == "kill_switch"
        assert position.notional == 0.0

    def test_run_bot_stands_down_when_the_day_loss_limit_is_breached(self, tmp_path):
        config = make_config(tmp_path, limits=RiskLimits(max_daily_loss_pct=0.03))
        make_data(config.data_dir)
        today = datetime.now(timezone.utc).date().isoformat()
        config.out_dir.mkdir(parents=True, exist_ok=True)
        state_path = Path(config.out_dir) / STATE_FILENAME
        state_path.write_text(
            json.dumps(
                {
                    "symbols": {},
                    "day": {"date": today, "pnl": -400.0, "funding": 0.0, "fees": 0.0},
                }
            )
        )
        result = run_bot(config)
        position = result["positions"][0]
        assert position.action == "NO_TRADE"
        assert position.reason == "daily_loss_limit"
        assert position.notional == 0.0

    def test_run_bot_honours_the_symbol_cap(self, tmp_path):
        config = make_config(
            tmp_path,
            symbols=("BTCUSDT", "ETHUSDT"),
            limits=RiskLimits(max_symbols=1),
        )
        make_data(config.data_dir, symbols=("BTCUSDT", "ETHUSDT"))
        result = run_bot(config)
        by_symbol = {position.symbol: position for position in result["positions"]}
        assert by_symbol["BTCUSDT"].action == "OPEN"
        assert by_symbol["ETHUSDT"].action == "NO_TRADE"
        assert by_symbol["ETHUSDT"].reason == "max_symbols"

    def test_run_bot_attaches_the_out_of_sample_validation(self, tmp_path):
        config = make_config(tmp_path, validate=True)
        make_data(config.data_dir, count=120)
        result = run_bot(config)
        validation = result["report"]["validation"]["BTCUSDT"]
        assert validation["verdict"]
        assert "frozen" in validation
        assert "out_of_sample" in validation["frozen"]

    def test_run_bot_writes_the_full_validation_artifact(self, tmp_path):
        config = make_config(tmp_path, validate=True)
        make_data(config.data_dir, count=120)
        result = run_bot(config)
        payload = json.loads(result["paths"]["validation"].read_text())
        assert payload["BTCUSDT"]["frozen"]["out_of_sample"]["prints"]

    def test_run_bot_raises_when_the_data_is_missing(self, tmp_path):
        config = make_config(tmp_path)
        with pytest.raises(FileNotFoundError):
            run_bot(config)

    def test_run_bot_reports_the_data_summary(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir, count=40)
        result = run_bot(config)
        summary = result["report"]["data_summary"]
        assert summary["BTCUSDT"]["prints"] == 40

    def test_run_bot_writes_the_archive_reconciliation_artifact(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir, count=40)
        result = run_bot(config)
        assert result["paths"]["reconciliation"].exists()
        payload = json.loads(result["paths"]["reconciliation"].read_text())
        assert payload["BTCUSDT"]["status"]

    def test_run_bot_attaches_the_reconciliation_to_the_report(self, tmp_path):
        config = make_config(tmp_path)
        make_data(config.data_dir, count=40)
        result = run_bot(config)
        reconciliation = result["report"]["reconciliation"]
        assert reconciliation["BTCUSDT"]["status"]


class TestRunBotRegime:
    def test_volatile_regime_stands_down(self, tmp_path):
        config = make_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 150)
        write_prices(config.data_dir, "BTCUSDT", n_bars=5000, vol=0.05, seed=7)
        result = run_bot(config)
        position = result["positions"][0]
        assert position.action == "NO_TRADE"
        assert position.side == 0

    def test_trend_regime_opens(self, tmp_path):
        config = make_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 150)
        write_prices(config.data_dir, "BTCUSDT", n_bars=5000, drift=0.002, vol=0.001, seed=3)
        result = run_bot(config)
        position = result["positions"][0]
        assert position.action == "OPEN"
        assert position.side == 1

    def test_mean_reversion_regime_collects(self, tmp_path):
        config = make_config(tmp_path)
        write_funding(config.data_dir, "BTCUSDT", [0.0001] * 150)
        write_prices(config.data_dir, "BTCUSDT", n_bars=5000, vol=0.001, drift=0.0, seed=5)
        result = run_bot(config)
        position = result["positions"][0]
        assert position.action == "OPEN"
        assert position.side == 1


class TestMain:
    def test_main_returns_zero_on_success(self, tmp_path, capsys):
        data_dir = tmp_path / "data"
        out_dir = tmp_path / "out"
        make_data(data_dir)
        code = main(
            [
                "--symbols",
                "BTCUSDT",
                "--data-dir",
                str(data_dir),
                "--out-dir",
                str(out_dir),
                "--no-validate",
            ]
        )
        assert code == 0
        assert "PAPER" in capsys.readouterr().out

    def test_main_returns_one_when_the_data_is_missing(self, tmp_path, capsys):
        code = main(
            [
                "--symbols",
                "BTCUSDT",
                "--data-dir",
                str(tmp_path / "empty"),
                "--out-dir",
                str(tmp_path / "out"),
                "--no-validate",
            ]
        )
        assert code == 1
        assert "BTCUSDT" in capsys.readouterr().err


def test_apply_position_keeps_the_book_when_a_target_is_not_filled():
    """A rejected or rolled-back target must not corrupt the paper book."""
    working = {"BTCUSDT": {"side": 1, "notional": 500.0, "last_funding_ts_ms": 1_000}}
    position = PaperPosition(
        "BTCUSDT", "OPEN", 1, 999.0, "risk_rejected", "candidate"
    )
    _apply_position(working, "BTCUSDT", position, filled=False)
    assert working["BTCUSDT"]["side"] == 1
    assert working["BTCUSDT"]["notional"] == 500.0
    assert working["BTCUSDT"]["last_funding_ts_ms"] == 1_000
    # last_action/last_reason are still recorded so rejections stay visible.
    assert working["BTCUSDT"]["last_action"] == "OPEN"
    assert working["BTCUSDT"]["last_reason"] == "risk_rejected"


def test_restored_governor_book_mirrors_the_paper_book():
    governor = RiskGovernor(risk_limits_for(RiskLimits(), EQUITY))
    _restore_governor_book(
        governor,
        {
            "BTCUSDT": {"side": 1, "notional": 5_000.0},
            "ETHUSDT": {"side": -1, "notional": 3_000.0},
            "SOLUSDT": {"side": 0, "notional": 0.0},
        },
    )
    assert governor.limits.positions["BTCUSDT"]["gross_notional"] == 10_000.0
    assert governor.limits.positions["ETHUSDT"]["gross_notional"] == 6_000.0
    assert "SOLUSDT" not in governor.limits.positions


def test_restored_book_blocks_a_second_carry_via_total_exposure():
    """A restored carry must count toward the governor's total exposure."""
    limits = RiskLimits(max_gross_notional=5_000.0, max_symbol_notional=5_000.0)

    # With no book restored, the new target fits easily.
    fresh = RiskGovernor(risk_limits_for(limits, EQUITY))
    approved, _ = approve_target(
        fresh, "ETHUSDT", 2_000.0, EQUITY, per_leg_notional=1_000.0
    )
    assert approved is True

    # Restoring the existing BTCUSDT carry makes the same target breach the
    # total-exposure cap, so it must be rejected and leave no allocation.
    governor = RiskGovernor(risk_limits_for(limits, EQUITY))
    _restore_governor_book(governor, {"BTCUSDT": {"side": 1, "notional": 5_000.0}})
    approved, reason = approve_target(
        governor, "ETHUSDT", 2_000.0, EQUITY, per_leg_notional=1_000.0
    )
    assert approved is False
    assert "total exposure" in reason
    assert "ETHUSDT" not in governor.limits.positions


def test_run_bot_stands_down_second_symbol_when_restored_book_is_full(tmp_path):
    config = make_config(
        tmp_path,
        symbols=("BTCUSDT", "ETHUSDT"),
        limits=RiskLimits(max_gross_notional=6_000.0, max_symbol_notional=6_000.0),
    )
    make_data(config.data_dir, symbols=("BTCUSDT", "ETHUSDT"))
    today = datetime.now(timezone.utc).date().isoformat()
    config.out_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(config.out_dir) / STATE_FILENAME
    state_path.write_text(
        json.dumps(
            {
                "symbols": {"BTCUSDT": {"side": 1, "notional": 5_000.0}},
                "day": {"date": today, "pnl": 0.0, "funding": 0.0, "fees": 0.0},
            }
        )
    )
    result = run_bot(config)
    eth = result["state"]["ETHUSDT"]
    assert eth["side"] == 0
    assert eth["notional"] == 0.0
    # The restored BTCUSDT carry exhausts the gross cap, so the second symbol
    # is stood down by the emitter and no allocation is made.
    assert eth["last_action"] == "NO_TRADE"
    assert eth["last_reason"] == "risk_cap_exhausted"
    btc = result["state"]["BTCUSDT"]
    assert btc["side"] == 1
    assert btc["notional"] == 6_000.0
