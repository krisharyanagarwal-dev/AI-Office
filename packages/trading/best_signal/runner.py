"""One-command runner for the best-signal bot.

``python -m best_signal.runner`` loads the evidence registry, reads the
archived funding history, emits paper targets, runs the pre-registered
out-of-sample validation and writes every artifact. The runner holds no
exchange credential and cannot place an order.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from best_signal.evidence import CandidateRecord, default_registry, select_tradable
from best_signal.execution import (
    ACTION_CLOSE,
    ACTION_FLIP,
    ACTION_HOLD,
    ACTION_NO_TRADE,
    ACTION_OPEN,
    CarryPaperBroker,
    ExecutionEngine,
    ExecutionResult,
    build_paper_venue,
    load_price_at,
    restore_venue,
    risk_limits_for,
    run_paper_execution,
    venue_snapshot,
)
from best_signal.funding import (
    FundingPrint,
    annualized_funding,
    load_symbol_prints,
    positive_print_fraction,
)
from best_signal.position import RiskLimits, build_paper_position
from best_signal.report import build_report, jsonable, write_report
from best_signal.rules import AlwaysOnCarry, PersistenceFlipCarry, RegimeFilteredCarry
from best_signal.validate import Candidate, reconcile_archive_audit, validate_candidate
from risk import RiskGovernor

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
STATE_FILENAME = "best_signal_state.json"
VALIDATION_FILENAME = "best_signal_validation.json"
RECONCILIATION_FILENAME = "best_signal_reconciliation.json"
SIGNALS_FILENAME = "best_signal_signals.json"
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "reports" / "best_signal"

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


def _symbol_summary(symbol: str, prints: list[FundingPrint]) -> dict:
    return {
        "prints": len(prints),
        "first_ts_ms": prints[0].ts_ms if prints else None,
        "last_ts_ms": prints[-1].ts_ms if prints else None,
        "annualized_funding": annualized_funding(prints),
        "positive_print_fraction": positive_print_fraction(prints),
    }


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


def _apply_position(working: dict, symbol: str, position) -> None:
    entry = dict(working.get(symbol, {"side": 0, "notional": 0.0}))
    entry["last_action"] = position.action
    entry["last_reason"] = position.reason
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
    engine, broker = build_paper_venue(equity)
    if state.get("venue"):
        restore_venue(broker, state["venue"])
    governor = RiskGovernor(risk_limits_for(config.limits, equity))
    governor.limits.daily_pnl = day_state["pnl"]

    price = 0.0
    for symbol in config.symbols:
        prints = load_symbol_prints(symbol, data_dir=config.data_dir)
        prints_by_symbol[symbol] = prints
        current = working.get(symbol)
        if current is None:
            current = {"side": 0, "notional": 0.0}
            working[symbol] = current
        gross_notional = sum(
            float(entry.get("notional", 0.0))
            for entry in working.values()
            if int(entry.get("side", 0)) != 0
        )
        open_symbols = sum(
            1 for entry in working.values() if int(entry.get("side", 0)) != 0
        )
        daily_loss_pct = day_state["pnl"] / equity if equity > 0 else 0.0
        position = build_paper_position(
            symbol,
            prints,
            records,
            config.limits,
            equity=config.equity,
            current_side=int(current.get("side", 0)),
            current_notional=float(current.get("notional", 0.0)),
            gross_notional=gross_notional,
            open_symbols=open_symbols,
            daily_loss_pct=daily_loss_pct,
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
        day_state["fees"] += result.fees
        day_state["pnl"] = (
            day_state["funding"]
            - day_state["fees"]
            + sum(broker.realized_pnl.values())
            - realised_before
        )

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

        _apply_position(working, symbol, position)
        data_summary[symbol] = _symbol_summary(symbol, prints)

        if config.validate and selected is not None:
            candidate = _candidate_for(selected)
            if candidate is not None:
                result = validate_candidate(candidate, prints)
                validations[symbol] = result
                validation_payload[symbol] = result

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
    parser.add_argument("--kill-switch", action="store_true")
    parser.add_argument(
        "--no-validate",
        dest="validate",
        action="store_false",
        help="skip the out-of-sample validation run",
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
