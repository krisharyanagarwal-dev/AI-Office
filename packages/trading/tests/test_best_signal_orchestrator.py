"""Tests for the unified paper-trading control plane orchestrator.

Covers the paper-mode cycle, kill-switch stand-down, start/stop control,
SQLite ``last_run`` persistence, and the consolidated portfolio snapshot the
unified API serves from the single StateStore. Paper mode only: no live
venue, no credentials, no exchange access.
"""
from __future__ import annotations

import pandas as pd
import pytest

from alpha.brain.orchestrator import Orchestrator, OrchestratorConfig
from alpha.brain.state_store import StateStore
from best_signal.position import RiskLimits

ALL_IN_ONE = "all_in_one"


def write_control_state(db_path, action=None, kill_switch=None, risk_limits=None):
    """Persist bot_control / risk_limits the way the unified API writes them."""
    store = StateStore({"path": db_path})
    try:
        if action is not None or kill_switch is not None:
            store.set(
                "bot_control",
                {"action": action, "killSwitch": kill_switch, "requestedAt": None, "updatedAt": None},
                category=ALL_IN_ONE,
            )
        if risk_limits is not None:
            store.set("risk_limits", risk_limits, category=ALL_IN_ONE)
    finally:
        store.close()

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


def write_prices(data_dir, symbol, count, price=100.0, start_ms=START_MS):
    data_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "open_time": [start_ms + index * FIFTEEN_MIN_MS for index in range(count)],
            "close": [price] * count,
        }
    )
    frame.to_parquet(data_dir / f"{symbol}_15m.parquet")


def write_market_data(data_dir, symbols=("BTCUSDT",), count=81, rate=0.0001):
    for symbol in symbols:
        write_funding(data_dir, symbol, [rate] * count)
        write_prices(data_dir, symbol, count)


def make_orchestrator(tmp_path, **overrides):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    settings = {
        "db_path": str(tmp_path / "state" / "all_in_one_state.db"),
        "symbols": ("BTCUSDT",),
        "data_dir": data_dir,
        "out_dir": out_dir,
        "equity": EQUITY,
        "limits": RiskLimits(),
        "validate": False,
        "kill_switch": False,
    }
    settings.update(overrides)
    return Orchestrator(OrchestratorConfig(**settings))


class TestPaperMode:
    def test_run_cycle_runs_best_signal_in_paper_mode(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        session = orch.run_cycle()
        orch.close()

        bot = session["bots"]["best_signal"]
        assert session["paper_only"] is True
        assert session["kill_switch"] is False
        assert bot["status"] == "ok"
        assert bot["mode"] == "paper"
        assert bot["execution_enabled"] is False
        assert bot["live"] is False
        assert bot["symbols"]["BTCUSDT"]["action"] == "OPEN"
        assert bot["symbols"]["BTCUSDT"]["side"] == 1
        assert bot["symbols"]["BTCUSDT"]["notional"] == pytest.approx(EQUITY)
        for entry in bot["positions"].values():
            assert entry["mode"] == "PAPER"
            assert entry["live"] is False

    def test_second_cycle_holds_instead_of_reopening(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        first = orch.run_cycle()
        second = orch.run_cycle()
        orch.close()

        assert first["symbols"]["BTCUSDT"]["action"] == "OPEN"
        assert second["symbols"]["BTCUSDT"]["action"] == "HOLD"
        assert second["symbols"]["BTCUSDT"]["side"] == 1

    def test_multiple_symbols_each_get_a_position_entry(self, tmp_path):
        orch = make_orchestrator(tmp_path, symbols=("BTCUSDT", "ETHUSDT"))
        write_market_data(orch.config.data_dir, symbols=("BTCUSDT", "ETHUSDT"))

        session = orch.run_cycle()
        orch.close()

        by_symbol = session["bots"]["best_signal"]["symbols"]
        assert set(by_symbol) == {"BTCUSDT", "ETHUSDT"}
        assert by_symbol["BTCUSDT"]["action"] == "OPEN"
        assert by_symbol["ETHUSDT"]["action"] == "OPEN"


class TestKillSwitch:
    def test_kill_switch_stands_down_every_symbol(self, tmp_path):
        orch = make_orchestrator(tmp_path, kill_switch=True)
        write_market_data(orch.config.data_dir)

        session = orch.run_cycle()
        orch.close()

        assert session["kill_switch"] is True
        bot = session["bots"]["best_signal"]
        assert bot["symbols"]["BTCUSDT"]["action"] == "NO_TRADE"
        assert bot["symbols"]["BTCUSDT"]["side"] == 0
        assert bot["symbols"]["BTCUSDT"]["notional"] == 0.0
        assert "kill_switch" in bot["symbols"]["BTCUSDT"]["reason"]

    def test_kill_switch_toggle_stands_down_and_rearms(self, tmp_path):
        off = make_orchestrator(tmp_path / "off")
        write_market_data(off.config.data_dir)
        assert off.run_cycle()["symbols"]["BTCUSDT"]["action"] == "OPEN"
        off.close()

        on = make_orchestrator(tmp_path / "on", kill_switch=True)
        write_market_data(on.config.data_dir)
        assert on.run_cycle()["symbols"]["BTCUSDT"]["action"] == "NO_TRADE"
        on.close()

        again = make_orchestrator(tmp_path / "again")
        write_market_data(again.config.data_dir)
        assert again.run_cycle()["symbols"]["BTCUSDT"]["action"] == "OPEN"
        again.close()


class TestStartStop:
    def test_start_runs_a_cycle_and_leaves_the_orchestrator_stopped(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        session = orch.start()
        assert orch.is_running is False
        assert session["bots"]["best_signal"]["status"] == "ok"
        orch.close()

    def test_start_while_already_running_returns_early(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        orch.running = True
        result = orch.start()
        assert result == {"status": "already_running", "run_id": orch.run_id}
        assert orch.is_running is True
        orch.running = False
        orch.close()

    def test_stop_stands_the_orchestrator_down(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        orch.running = True

        result = orch.stop()
        assert result == {"status": "stopped", "run_id": orch.run_id}
        assert orch.is_running is False
        orch.close()


class TestStatePersistence:
    def test_run_cycle_persists_last_run_to_the_sqlite_store(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        session = orch.run_cycle()

        consolidated = orch.get_consolidated_state()
        assert consolidated["mode"] == "paper"
        assert consolidated["execution_enabled"] is False
        assert consolidated["live"] is False
        assert consolidated["live_trading"] is False
        assert consolidated["status"] == "ok"
        assert consolidated["portfolio"] == session["portfolio"]
        assert consolidated["session"]["run_id"] == session["run_id"]

        # The same record is readable straight from the StateStore, which is
        # the unified API's source of truth.
        store = StateStore({"path": orch.config.db_path})
        try:
            raw = store.get("last_run", category="all_in_one")
        finally:
            store.close()
        assert raw["mode"] == "paper"
        assert raw["portfolio"]["broker"] == "paper"

    def test_consolidated_state_survives_orchestrator_reconstruction(self, tmp_path):
        db_path = str(tmp_path / "state" / "all_in_one_state.db")
        data_dir = tmp_path / "data"
        out_dir = tmp_path / "out"
        write_market_data(data_dir)

        first = Orchestrator(
            OrchestratorConfig(
                db_path=db_path,
                data_dir=data_dir,
                out_dir=out_dir,
                symbols=("BTCUSDT",),
            )
        )
        first.run_cycle()
        first.close()

        second = Orchestrator(
            OrchestratorConfig(
                db_path=db_path,
                data_dir=data_dir,
                out_dir=out_dir,
                symbols=("BTCUSDT",),
            )
        )
        state = second.get_consolidated_state()
        second.close()

        assert state["status"] == "ok"
        assert state["session"]["symbols"]["BTCUSDT"]["action"] == "OPEN"

    def test_consolidated_state_is_empty_before_any_run(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        assert orch.get_consolidated_state() == {}
        orch.close()


class TestPortfolioSnapshot:
    def test_portfolio_snapshot_matches_unified_api_shape(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        orch.run_cycle()
        portfolio = orch.last_portfolio
        orch.close()

        assert portfolio["broker"] == "paper"
        assert portfolio["currency"] == "USDT"
        assert portfolio["cash"] == pytest.approx(EQUITY)
        assert portfolio["equity"] == pytest.approx(EQUITY)
        assert portfolio["market_value"] == 0.0
        assert portfolio["realized_pnl"] == 0.0
        assert portfolio["unrealized_pnl"] == 0.0
        assert portfolio["total_pnl"] == 0.0
        assert portfolio["peak_equity"] == pytest.approx(EQUITY)
        assert portfolio["max_drawdown"] == 0.0
        assert portfolio["drawdown"] == 0.0
        assert portfolio["timestamp"] > 0

        position = portfolio["positions"]["BTCUSDT"]
        for key in ("quantity", "avg_entry_price", "mark_price", "unrealized_pnl", "realized_pnl"):
            assert key in position

    def test_session_symbols_match_portfolio_positions(self, tmp_path):
        orch = make_orchestrator(tmp_path, symbols=("BTCUSDT", "ETHUSDT"))
        write_market_data(orch.config.data_dir, symbols=("BTCUSDT", "ETHUSDT"))

        session = orch.run_cycle()
        orch.close()

        assert set(session["portfolio"]["positions"]) == {"BTCUSDT", "ETHUSDT"}
        assert set(session["symbols"]) == {"BTCUSDT", "ETHUSDT"}


class TestMissingData:
    def test_missing_data_returns_an_error_instead_of_raising(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        # No funding or price files under data_dir.

        session = orch.run_cycle()
        orch.close()

        assert session["bots"]["best_signal"]["status"] == "error"
        assert "data unavailable" in session["bots"]["best_signal"]["error"]
        assert session["portfolio"]["positions"] == {}


class TestControlState:
    def test_kill_switch_from_state_store_stands_down_best_signal(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)
        write_control_state(orch.config.db_path, kill_switch=True)

        session = orch.run_cycle()
        orch.close()

        assert session["kill_switch"] is True
        assert session["symbols"]["BTCUSDT"]["action"] == "NO_TRADE"
        assert session["symbols"]["BTCUSDT"]["side"] == 0
        assert session["symbols"]["BTCUSDT"]["notional"] == 0.0
        assert "kill_switch" in session["symbols"]["BTCUSDT"]["reason"]

    def test_stop_action_from_state_store_stands_down_every_symbol(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)
        write_control_state(orch.config.db_path, action="stop")

        session = orch.run_cycle()
        orch.close()

        assert session["bots"]["best_signal"]["status"] == "ok"
        assert session["symbols"]["BTCUSDT"]["action"] == "NO_TRADE"
        assert session["symbols"]["BTCUSDT"]["side"] == 0
        assert session["symbols"]["BTCUSDT"]["notional"] == 0.0
        assert session["symbols"]["BTCUSDT"]["reason"] == "stopped"

    def test_risk_limits_from_state_store_cap_symbol_notional(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)
        write_control_state(orch.config.db_path, risk_limits={"max_symbol_notional": 500.0})

        session = orch.run_cycle()
        orch.close()

        assert session["symbols"]["BTCUSDT"]["action"] == "OPEN"
        assert session["symbols"]["BTCUSDT"]["notional"] == pytest.approx(500.0)

    def test_risk_limits_from_state_store_exhaust_gross_cap(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)
        write_control_state(orch.config.db_path, risk_limits={"max_gross_notional": 0.0})

        session = orch.run_cycle()
        orch.close()

        assert session["symbols"]["BTCUSDT"]["action"] == "NO_TRADE"
        assert session["symbols"]["BTCUSDT"]["reason"] == "risk_cap_exhausted"

    def test_zero_max_symbols_from_state_store_stands_down(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)
        write_control_state(orch.config.db_path, risk_limits={"max_symbols": 0})

        session = orch.run_cycle()
        orch.close()

        assert session["symbols"]["BTCUSDT"]["action"] == "NO_TRADE"
        assert session["symbols"]["BTCUSDT"]["reason"] == "max_symbols"

    def test_control_state_is_optional_and_defaults_apply(self, tmp_path):
        orch = make_orchestrator(tmp_path)
        write_market_data(orch.config.data_dir)

        session = orch.run_cycle()
        orch.close()

        assert session["symbols"]["BTCUSDT"]["action"] == "OPEN"
        assert session["symbols"]["BTCUSDT"]["notional"] == pytest.approx(10_000.0)
