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

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
STATE_FILENAME = "best_signal_state.json"
VALIDATION_FILENAME = "best_signal_validation.json"
RECONCILIATION_FILENAME = "best_signal_reconciliation.json"
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
    if position.action == "NO_TRADE":
        entry = dict(working.get(symbol, {"side": 0, "notional": 0.0}))
        entry["last_action"] = position.action
        entry["last_reason"] = position.reason
        working[symbol] = entry
        return
    if position.action == "CLOSE":
        working[symbol] = {
            "side": 0,
            "notional": 0.0,
            "last_action": position.action,
            "last_reason": position.reason,
        }
        return
    working[symbol] = {
        "side": position.side,
        "notional": position.notional,
        "last_action": position.action,
        "last_reason": position.reason,
    }


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
    validations = {}
    validation_payload = {}
    data_summary = {}
    prints_by_symbol = {}

    for symbol in config.symbols:
        prints = load_symbol_prints(symbol, data_dir=config.data_dir)
        prints_by_symbol[symbol] = prints
        current = working.get(symbol, {"side": 0, "notional": 0.0})
        gross_notional = sum(
            float(entry.get("notional", 0.0))
            for entry in working.values()
            if int(entry.get("side", 0)) != 0
        )
        open_symbols = sum(
            1 for entry in working.values() if int(entry.get("side", 0)) != 0
        )
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
            daily_loss_pct=config.daily_loss_pct,
        )
        positions.append(position)
        _apply_position(working, symbol, position)
        data_summary[symbol] = _symbol_summary(symbol, prints)

        if config.validate and selected is not None:
            candidate = _candidate_for(selected)
            if candidate is not None:
                result = validate_candidate(candidate, prints)
                validations[symbol] = result
                validation_payload[symbol] = result

    reconciliation = reconcile_archive_audit(prints_by_symbol)

    report = build_report(
        records,
        positions,
        validations=validations,
        data_summary=data_summary,
        reconciliation=reconciliation,
    )
    paths = write_report(report, out_dir)

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
            "mode": "PAPER",
            "live": False,
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
