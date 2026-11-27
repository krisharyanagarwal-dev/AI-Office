"""One-command runner for the best-signal bot.

``python -m best_signal.runner`` loads the evidence registry, reads the
archived funding history, emits paper targets, runs the pre-registered
out-of-sample validation and writes every artifact. The runner holds no
exchange credential and cannot place an order.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from best_signal.evidence import CandidateRecord, default_registry, select_tradable
from best_signal.execution import (
    ACTION_CLOSE,
    ACTION_FLIP,
    ACTION_HOLD,
    ACTION_NO_TRADE,
    ACTION_OPEN,
    CarryPaperBroker,
    ExecutionEngine,
    ExecutionRealismConfig,
    ExecutionResult,
    build_paper_venue,
    load_price_at,
    restore_venue,
    risk_limits_for,
    run_paper_execution,
    venue_snapshot,
)
from best_signal.fill_journal import FillJournal
from best_signal.telemetry import CycleMetrics, TelemetrySink, record_cycle
from best_signal.funding import (
    DEFAULT_DATA_DIR,
    FundingPrint,
    annualized_funding,
    load_symbol_prints,
    positive_print_fraction,
)
from best_signal.position import PaperPosition, RiskLimits, build_paper_position
from best_signal.portfolio_sizer import SizingInput, SizingResult, compute_target_notionals
from best_signal.report import build_report, jsonable, write_report
from best_signal.rules import AlwaysOnCarry, PersistenceFlipCarry, RegimeFilteredCarry
from best_signal.validate import Candidate, reconcile_archive_audit, validate_candidate
from risk import RiskGovernor

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
STATE_FILENAME = "best_signal_state.json"
VALIDATION_FILENAME = "best_signal_validation.json"
RECONCILIATION_FILENAME = "best_signal_reconciliation.json"
SIGNALS_FILENAME = "best_signal_signals.json"
TELEMETRY_FILENAME = "best_signal_telemetry.jsonl"
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "reports" / "best_signal"

logger = logging.getLogger(__name__)

VALIDATION_RULES = {
    "always_on_carry": lambda params: AlwaysOnCarry(),
    "regime_filtered_carry": lambda params: RegimeFilteredCarry(**params),
    "persistence_flip_carry": lambda params: PersistenceFlipCarry(**params),
}

PARAM_GRIDS = {
    "always_on_carry": [{}],
    "regime_filtered_carry": [
        {"lookback_prints": lookback, "stand_down_ann": 0.0, "reenter_ann": reenter}
        for lookback in (20, 30, 60)
        for reenter in (0.0, 0.03, 0.06)
    ],
    "persistence_flip_carry": [
        {"persistence_hours": hours, "threshold": threshold}
        for hours in (24.0, 48.0, 72.0)
        for threshold in (1e-05, 5e-05, 1e-04)
    ],
}


@dataclass(frozen=True)
class BotConfig:
    """Everything one bot run needs."""

    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    data_dir: Path | None = None
    out_dir: Path = DEFAULT_OUT_DIR
    state_path: Path | None = None
    equity: float = 10_000.0
    limits: RiskLimits = RiskLimits()
    validate: bool = True
    daily_loss_pct: float = 0.0
    execution_realism: ExecutionRealismConfig = ExecutionRealismConfig()
    telemetry_enabled: bool = True
    fill_journal_enabled: bool = True


@dataclass(frozen=True)
class ExecutionSummary:
    """Aggregated execution summary for a bot run."""

    period: str
    start_ts: int
    end_ts: int
    total_fills: int
    total_volume: float
    avg_slippage_bps: float
    slippage_p50_bps: float
    slippage_p95_bps: float
    avg_latency_ms: float
    partial_fill_rate: float
    total_fees: float
    fees_vs_slippage_bps: float
    by_symbol: dict[str, dict]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {"symbols": {}}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"corrupt state file {path}: {error}") from error
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict):
        raise ValueError(f"corrupt state file {path}: 'symbols' must be an object")
    return payload


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, path)


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) of a list of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def _compute_execution_summary(
    fill_journal_path: Path,
    telemetry_path: Path,
    start_ts: int,
    end_ts: int,
) -> ExecutionSummary:
    """Read fills.jsonl and telemetry.jsonl, compute aggregates and percentiles."""
    from best_signal.fill_journal import FillRecord
    from best_signal.telemetry import CycleMetrics
    
    fills = []
    if fill_journal_path.exists():
        with fill_journal_path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    fills.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    
    cycles = []
    if telemetry_path.exists():
        with telemetry_path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    cycles.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    
    if not fills and not cycles:
        # No data, return empty summary
        return ExecutionSummary(
            period=f"{datetime.fromtimestamp(start_ts/1000, tz=timezone.utc).isoformat()}/"
                   f"{datetime.fromtimestamp(end_ts/1000, tz=timezone.utc).isoformat()}",
            start_ts=start_ts,
            end_ts=end_ts,
            total_fills=0,
            total_volume=0.0,
            avg_slippage_bps=0.0,
            slippage_p50_bps=0.0,
            slippage_p95_bps=0.0,
            avg_latency_ms=0.0,
            partial_fill_rate=0.0,
            total_fees=0.0,
            fees_vs_slippage_bps=0.0,
            by_symbol={},
        )
    
    # Aggregate from fills
    slippages = [f.get("slippage_bps", 0.0) for f in fills]
    latencies = [f.get("latency_ms", 0.0) for f in fills]
    venue_latencies = [f.get("venue_latency_ms", 0.0) for f in fills]
    partial_fills = [f for f in fills if f.get("partial_fill", False)]
    fees = [f.get("fees", 0.0) for f in fills]
    volumes = [f.get("quantity", 0.0) * f.get("price", 0.0) for f in fills]
    
    # By-symbol breakdown
    by_symbol = {}
    for symbol in set(f.get("symbol", "") for f in fills):
        symbol_fills = [f for f in fills if f.get("symbol") == symbol]
        symbol_slippages = [f.get("slippage_bps", 0.0) for f in symbol_fills]
        symbol_fees = [f.get("fees", 0.0) for f in symbol_fills]
        symbol_volumes = [f.get("quantity", 0.0) * f.get("price", 0.0) for f in symbol_fills]
        symbol_partials = [f for f in symbol_fills if f.get("partial_fill", False)]
        symbol_latencies = [f.get("latency_ms", 0.0) for f in symbol_fills]
        symbol_venue_latencies = [f.get("venue_latency_ms", 0.0) for f in symbol_fills]
        
        by_symbol[symbol] = {
            "fills": len(symbol_fills),
            "volume": sum(symbol_volumes),
            "avg_slippage_bps": sum(symbol_slippages) / len(symbol_slippages) if symbol_slippages else 0.0,
            "slippage_p50_bps": _percentile(symbol_slippages, 50) if symbol_slippages else 0.0,
            "slippage_p95_bps": _percentile(symbol_slippages, 95) if symbol_slippages else 0.0,
            "avg_latency_ms": sum(symbol_latencies) / len(symbol_latencies) if symbol_latencies else 0.0,
            "avg_venue_latency_ms": sum(symbol_venue_latencies) / len(symbol_venue_latencies) if symbol_venue_latencies else 0.0,
            "partial_fill_rate": len(symbol_partials) / len(symbol_fills) if symbol_fills else 0.0,
            "total_fees": sum(symbol_fees),
        }
    
    total_fills = len(fills)
    total_volume = sum(volumes)
    avg_slippage_bps = sum(slippages) / len(slippages) if slippages else 0.0
    slippage_p50_bps = _percentile(slippages, 50) if slippages else 0.0
    slippage_p95_bps = _percentile(slippages, 95) if slippages else 0.0
    # Use venue_latency_ms if available, otherwise latency_ms
    all_latencies = [v for v in venue_latencies if v > 0] or latencies
    avg_latency_ms = sum(all_latencies) / len(all_latencies) if all_latencies else 0.0
    partial_fill_rate = len(partial_fills) / total_fills if total_fills > 0 else 0.0
    total_fees = sum(fees)
    
    # fees_vs_slippage_bps: fees as bps of total volume
    fees_vs_slippage_bps = (total_fees / total_volume * 10000) if total_volume > 0 else 0.0
    
    period_start = datetime.fromtimestamp(start_ts / 1000, tz=timezone.utc).isoformat()
    period_end = datetime.fromtimestamp(end_ts / 1000, tz=timezone.utc).isoformat()
    period = f"{period_start}/{period_end}"
    
    return ExecutionSummary(
        period=period,
        start_ts=start_ts,
        end_ts=end_ts,
        total_fills=total_fills,
        total_volume=total_volume,
        avg_slippage_bps=avg_slippage_bps,
        slippage_p50_bps=slippage_p50_bps,
        slippage_p95_bps=slippage_p95_bps,
        avg_latency_ms=avg_latency_ms,
        partial_fill_rate=partial_fill_rate,
        total_fees=total_fees,
        fees_vs_slippage_bps=fees_vs_slippage_bps,
        by_symbol=by_symbol,
    )


def _symbol_summary(symbol: str, prints: list[FundingPrint]) -> dict:
    return {
        "prints": len(prints),
        "first_ts_ms": prints[0].ts_ms if prints else None,
        "last_ts_ms": prints[-1].ts_ms if prints else None,
        "annualized_funding": annualized_funding(prints),
        "positive_print_fraction": positive_print_fraction(prints),
    }


def _causal_price_returns(
    symbol: str, prints: list[FundingPrint], data_dir: Path | None
) -> pd.Series:
    """Causal 15m close-to-close returns aligned to each funding print.

    The price used for print ``i`` is the last 15m close at or before print
    ``i``'s timestamp, so no regime decision can use future price information.
    Returns an empty series when the price file is unavailable, which leaves
    the rule's regime gate inactive (backward compatible).
    """
    if not prints:
        return pd.Series(dtype=float)
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    path = root / f"{symbol}_15m.parquet"
    if not path.is_file():
        return pd.Series(dtype=float)
    frame = pd.read_parquet(path)
    if "open_time" not in frame.columns or "close" not in frame.columns:
        return pd.Series(dtype=float)

    closes: list[float | None] = []
    for fp in prints:
        bars = frame[frame["open_time"] <= fp.ts_ms]
        if bars.empty:
            closes.append(None)
        else:
            closes.append(
                float(bars.sort_values("open_time")["close"].iloc[-1])
            )
    series = pd.Series(closes, index=[fp.ts_ms for fp in prints]).dropna()
    if series.empty:
        return pd.Series(dtype=float)
    return series.pct_change().fillna(0.0)


def _candidate_for(record: CandidateRecord) -> Candidate | None:
    factory = VALIDATION_RULES.get(record.rule_key)
    if factory is None:
        return None
    return Candidate(
        name=record.name,
        thesis=record.thesis,
        rule_factory=factory,
        param_grid=PARAM_GRIDS.get(record.rule_key, [{}]),
        kind=record.kind,
    )


def _restore_governor_book(governor: RiskGovernor, working: dict) -> None:
    """Rebuild the governor's position book from the restored paper state.

    A fresh governor starts with an empty book, but the emitter sizes each
    target against the carries ``working`` actually holds. Restoring the
    governor's book from the same state keeps its per-symbol and total
    exposure checks in sync with the book instead of judging each cycle
    against an empty slate.

    Note: gross_notional is stored as per-leg notional (matching the bot's
    max_symbol_notional cap) since governor limits are configured per-leg
    (Task 2: no 2x inflation).
    """
    for symbol, entry in working.items():
        if int(entry.get("side", 0)) == 0:
            continue
        governor.limits.positions[symbol] = {
            "quantity": 0.0,
            "avg_entry_price": 0.0,
            "gross_notional": float(entry.get("notional", 0.0)),
        }


def _apply_position(working: dict, symbol: str, position, filled: bool = True) -> None:
    entry = dict(working.get(symbol, {"side": 0, "notional": 0.0}))
    entry["last_action"] = position.action
    entry["last_reason"] = position.reason
    if not filled:
        # A risk-rejected or rolled-back target never reached the venue, so
        # the paper book keeps the position it actually holds instead of
        # recording an allocation the governor just refused.
        working[symbol] = entry
        return
    if position.action == "CLOSE":
        entry["side"] = 0
        entry["notional"] = 0.0
    elif position.action in (ACTION_OPEN, ACTION_HOLD, ACTION_FLIP):
        entry["side"] = position.side
        entry["notional"] = position.notional
    # NO_TRADE and any other action: side/notional unchanged so a live carry
    # is never liquidated by a stand-down, and last_funding_ts_ms is preserved.
    working[symbol] = entry


def run_bot(config: BotConfig) -> dict:
    """Run the bot end to end in paper mode and write every artifact."""
    start_ts = _now_ms()
    records = default_registry()
    selected = select_tradable(records)

    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(config.state_path) if config.state_path else out_dir / STATE_FILENAME
    state = _load_state(state_path)
    working = {
        symbol: dict(entry) for symbol, entry in (state.get("symbols") or {}).items()
    }

    positions = []
    signals = []
    validations = {}
    validation_payload = {}
    data_summary = {}
    prints_by_symbol = {}

    # Day bookkeeping: reset the day counters when the UTC date changes so a
    # losing day never stands the book down forever.
    today = datetime.now(timezone.utc).date().isoformat()
    day_state = dict(state.get("day") or {})
    if day_state.get("date") != today:
        day_state = {"date": today, "funding": 0.0, "fees": 0.0, "pnl": 0.0}

    equity = config.equity
    journal = FillJournal(out_dir / "best_signal_fills.jsonl", enabled=config.fill_journal_enabled)
    engine, broker = build_paper_venue(equity, realism=config.execution_realism, fill_journal=journal)
    if state.get("venue"):
        restore_venue(broker, state["venue"])
    sink = TelemetrySink(out_dir / TELEMETRY_FILENAME, enabled=config.telemetry_enabled)
    governor = RiskGovernor(risk_limits_for(config.limits, equity))
    governor.limits.daily_pnl = day_state["pnl"]
    governor.update_high_water_mark(equity + day_state["pnl"])
    _restore_governor_book(governor, working)

    # ===== PASS 1: Collect raw signals with zero notional =====
    sizing_inputs = []
    symbol_data = {}  # Store prints, returns, current state for pass 2

    # Compute actual gross_notional and open_symbols from working state for pass 1
    # (used for max_symbols check, but gross_notional=0 bypasses portfolio cap)
    actual_gross_notional = sum(
        float(entry.get("notional", 0.0))
        for entry in working.values()
        if int(entry.get("side", 0)) != 0
    )
    open_symbols = sum(
        1 for entry in working.values() if int(entry.get("side", 0)) != 0
    )
    daily_loss_pct = day_state["pnl"] / equity if equity > 0 else 0.0

    for symbol in config.symbols:
        prints = load_symbol_prints(symbol, data_dir=config.data_dir)
        returns = _causal_price_returns(symbol, prints, config.data_dir)
        prints_by_symbol[symbol] = prints
        current = working.get(symbol)
        if current is None:
            current = {"side": 0, "notional": 0.0}
            working[symbol] = current

        # Call build_paper_position with gross_notional=0 to get raw signal
        # but pass current open_symbols for max_symbols check (sequential allocation)
        raw_position = build_paper_position(
            symbol,
            prints,
            records,
            config.limits,
            equity=config.equity,
            current_side=int(current.get("side", 0)),
            current_notional=float(current.get("notional", 0.0)),
            gross_notional=0.0,  # Zero notional for pass 1 (bypass portfolio cap)
            open_symbols=open_symbols,  # Current open symbols for max_symbols check
            daily_loss_pct=daily_loss_pct,
            returns=returns,
        )

        # Determine candidate_score from candidate metrics if available
        candidate_score = 1.0
        if selected and selected.metrics:
            # Use symbol-specific metric if available, else default
            metric_key = f"{symbol.lower().replace('usdt', '')}_oos_net"
            if metric_key in selected.metrics:
                candidate_score = max(0.0, selected.metrics[metric_key])
            elif "btc_oos_net" in selected.metrics and "eth_oos_net" in selected.metrics:
                # Fallback to average if symbol-specific not found
                candidate_score = max(0.0, (selected.metrics.get("btc_oos_net", 0) + selected.metrics.get("eth_oos_net", 0)) / 2)

        sizing_inputs.append(SizingInput(
            symbol=symbol,
            side=raw_position.side,
            action=raw_position.action,
            current_notional=float(current.get("notional", 0.0)),
            candidate_score=candidate_score,
        ))

        # Store data needed for pass 2
        symbol_data[symbol] = {
            "prints": prints,
            "returns": returns,
            "current": current,
            "raw_position": raw_position,
        }

        # Update open_symbols for next symbol if this symbol wants to open/flip
        if raw_position.action in (ACTION_OPEN, ACTION_FLIP) and raw_position.side != 0:
            open_symbols += 1

        # Validation and data summary can be done in pass 1
        data_summary[symbol] = _symbol_summary(symbol, prints)
        if config.validate and selected is not None:
            candidate = _candidate_for(selected)
            if candidate is not None:
                result = validate_candidate(candidate, prints)
                validations[symbol] = result
                validation_payload[symbol] = result

    # ===== PASS 2: Portfolio sizing and execution =====
    # Compute target notionals using portfolio sizer
    sizing_results = compute_target_notionals(
        sizing_inputs,
        equity=config.equity,
        limits=config.limits,
        current_book=working,
    )

    # Create a mapping from symbol to SizingResult
    sizing_result_map = {r.symbol: r for r in sizing_results}

    price = 0.0
    for symbol in config.symbols:
        data = symbol_data[symbol]
        prints = data["prints"]
        returns = data["returns"]
        current = data["current"]
        raw_position = data["raw_position"]
        sizing_result = sizing_result_map[symbol]

        # Create final position with allocated notional
        position = PaperPosition(
            symbol=symbol,
            action=sizing_result.action,
            side=sizing_result.side,
            notional=sizing_result.target_notional,
            reason=raw_position.reason,
            candidate=raw_position.candidate,
        )
        positions.append(position)

        # Accrue funding for prints newer than the last accrued print, sized on
        # the notional the book actually carries (a stand-down keeps the carry,
        # so it keeps earning funding).
        last_funding_ts = int(current.get("last_funding_ts_ms") or 0)
        if last_funding_ts == 0 and len(prints) >= 2:
            # No prior record: accrue only the most recent funding period.
            last_funding_ts = prints[-2].ts_ms
        new_prints = [fp for fp in prints if fp.ts_ms > last_funding_ts]
        if new_prints:
            current["last_funding_ts_ms"] = max(fp.ts_ms for fp in new_prints)
        accrual_notional = (
            position.notional
            if position.side != 0
            else (
                float(current.get("notional", 0.0))
                if int(current.get("side", 0)) != 0
                else 0.0
            )
        )
        funding = sum(fp.rate for fp in new_prints) * accrual_notional
        day_state["funding"] += funding
        broker.balances["USDT"] = round(
            broker.balances.get("USDT", 0.0) + funding, 8
        )

        price, _source = load_price_at(symbol, _now_ms(), data_dir=config.data_dir)

        realised_before = sum(broker.realized_pnl.values())
        if position.action in (ACTION_OPEN, ACTION_FLIP, ACTION_CLOSE):
            result = run_paper_execution(
                engine,
                broker,
                symbol,
                position.side,
                position.notional,
                price,
                equity,
                governor=governor,
                action=position.action,
                current_side=int(current.get("side", 0)),
                current_notional=float(current.get("notional", 0.0)),
            )
        elif position.action == ACTION_HOLD:
            result = ExecutionResult(symbol, ACTION_HOLD, (), 0.0, True, "held")
        else:
            result = ExecutionResult(
                symbol, ACTION_NO_TRADE, (), 0.0, True, "stand_down"
            )
        record_cycle(
            sink,
            symbol,
            position.side,
            position.notional,
            position.action,
            result,
            broker,
        )
        day_state["fees"] += result.fees
        day_state["pnl"] = (
            day_state["funding"]
            - day_state["fees"]
            + sum(broker.realized_pnl.values())
            - realised_before
        )

        # Keep the risk governor's day bookkeeping in step with the day
        # state the position emitter reads, so its daily-loss and drawdown
        # checks decide on the same running P&L this cycle instead of a
        # stale snapshot from cycle start.
        governor.limits.daily_pnl = day_state["pnl"]
        governor.update_high_water_mark(equity + day_state["pnl"])

        # Send a signal when the emitted action changes the book: an OPEN, a
        # CLOSE, or a FLIP is a difference worth sending. Holding or standing
        # down with no change to the book is not a signal.
        if position.action in (ACTION_OPEN, ACTION_CLOSE, ACTION_FLIP):
            signals.append(
                {
                    "symbol": symbol,
                    "action": position.action,
                    "side": position.side,
                    "notional": position.notional,
                    "reason": position.reason,
                    "candidate": position.candidate,
                    "price": price,
                    "generated_at": _now(),
                }
            )

        _apply_position(working, symbol, position, filled=result.filled)

        # Defensive consistency check
        if governor is not None:
            gov_symbols = {
                s for s, p in governor.limits.positions.items() if p.get("gross_notional", 0) > 0
            }
            working_symbols = {
                s for s, w in working.items() if w.get("side", 0) != 0
            }
            if gov_symbols != working_symbols:
                logger.warning(
                    f"Governor/working divergence for {symbol}: "
                    f"gov={sorted(gov_symbols)} working={sorted(working_symbols)}"
                )

    reconciliation = reconcile_archive_audit(prints_by_symbol)
    venue = venue_snapshot(broker)

    report = build_report(
        records,
        positions,
        validations=validations,
        data_summary=data_summary,
        reconciliation=reconciliation,
        venue=venue,
        signals=signals,
    )
    paths = write_report(report, out_dir)

    signals_path = out_dir / SIGNALS_FILENAME
    _write_json(signals_path, signals)

    validation_path = out_dir / VALIDATION_FILENAME
    if validation_payload:
        _write_json(validation_path, jsonable(validation_payload))
    else:
        _write_json(validation_path, {"skipped": True})

    reconciliation_path = out_dir / RECONCILIATION_FILENAME
    _write_json(reconciliation_path, jsonable(reconciliation))

    _write_json(
        state_path,
        {
            "updated_at": _now(),
            "mode": "paper",
            "execution_enabled": False,
            "live_trading": False,
            "live": False,
            "status": "ok",
            "last_run": _now(),
            "positions": [position.to_dict() for position in positions],
            "closed": [],
            "realized_pnl": sum(broker.realized_pnl.values()),
            "price": price,
            "day": day_state,
            "venue": venue,
            "symbols": working,
        },
    )

    # Write execution summary
    end_ts = _now_ms()
    summary = _compute_execution_summary(
        out_dir / "best_signal_fills.jsonl",
        out_dir / TELEMETRY_FILENAME,
        start_ts,
        end_ts,
    )
    summary_path = out_dir / "execution_summary.json"
    _write_json(summary_path, asdict(summary))

    return {
        "report": report,
        "positions": positions,
        "state": working,
        "paths": {
            "json": paths["json"],
            "markdown": paths["markdown"],
            "state": state_path,
            "validation": validation_path,
            "reconciliation": reconciliation_path,
            "signals": signals_path,
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="best_signal.runner",
        description="Run the best-signal bot in paper mode. Places no orders.",
    )
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--state-file", default=None)
    parser.add_argument("--equity", type=float, default=10_000.0)
    parser.add_argument(
        "--max-symbol-notional", type=float, default=RiskLimits.max_symbol_notional
    )
    parser.add_argument(
        "--max-gross-notional", type=float, default=RiskLimits.max_gross_notional
    )
    parser.add_argument(
        "--max-position-weight", type=float, default=RiskLimits.max_position_weight
    )
    parser.add_argument("--max-symbols", type=int, default=RiskLimits.max_symbols)
    parser.add_argument(
        "--max-daily-loss-pct", type=float, default=RiskLimits.max_daily_loss_pct
    )
    parser.add_argument("--daily-loss-pct", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--latency-ms", type=float, default=0.0)
    parser.add_argument(
        "--partial-fill",
        dest="partial_fill",
        action="store_true",
        help="enable deterministic partial fills (paper mode only)",
    )
    parser.add_argument(
        "--partial-fill-fraction",
        type=float,
        default=ExecutionRealismConfig.partial_fill_fraction,
    )
    parser.add_argument("--kill-switch", action="store_true")
    parser.add_argument(
        "--no-validate",
        dest="validate",
        action="store_false",
        help="skip the out-of-sample validation run",
    )
    parser.add_argument(
        "--no-telemetry",
        dest="telemetry",
        action="store_false",
        help="disable paper-mode execution telemetry",
    )
    parser.add_argument(
        "--no-fill-journal",
        dest="fill_journal",
        action="store_false",
        help="disable paper-mode fill journal",
    )
    return parser


def main(argv=None) -> int:
    """Command-line entry point. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    limits = RiskLimits(
        max_symbol_notional=args.max_symbol_notional,
        max_gross_notional=args.max_gross_notional,
        max_position_weight=args.max_position_weight,
        max_symbols=args.max_symbols,
        max_daily_loss_pct=args.max_daily_loss_pct,
        kill_switch=args.kill_switch,
    )
    config = BotConfig(
        symbols=tuple(args.symbols),
        data_dir=Path(args.data_dir) if args.data_dir else None,
        out_dir=Path(args.out_dir),
        state_path=Path(args.state_file) if args.state_file else None,
        equity=args.equity,
        limits=limits,
        validate=args.validate,
        daily_loss_pct=args.daily_loss_pct,
        execution_realism=ExecutionRealismConfig(
            slippage_bps=args.slippage_bps,
            latency_ms=args.latency_ms,
            partial_fill_enabled=args.partial_fill,
            partial_fill_fraction=args.partial_fill_fraction,
        ),
        telemetry_enabled=args.telemetry,
        fill_journal_enabled=args.fill_journal,
    )
    try:
        result = run_bot(config)
    except FileNotFoundError as error:
        print(f"best-signal bot: data unavailable: {error}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f"best-signal bot: run failed: {error}", file=sys.stderr)
        return 1

    print("best-signal bot - PAPER mode, no orders placed")
    for position in result["positions"]:
        print(
            f"  {position.symbol}: {position.action} side={position.side} "
            f"notional={position.notional:.2f} reason={position.reason}"
        )
    print(f"  report: {result['paths']['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
