"""Leakage-safe out-of-sample validation for the best-signal bot.

Conventions
-----------
*Execution lag*: the side chosen for print ``i`` is decided from
``prints[:i]`` only, so no decision can use the rate it is charged for.
*Leg accounting*: opening or closing a position costs 2 taker legs, a sign
flip costs 4, and the short-spot leg pays borrow while it is held.
*Selection*: the parameter grid is ranked on the in-sample split only; the
winner is frozen before the validation and out-of-sample splits are read.
*Splits*: 60/15/25 of the records, in record order, at the native 8h print
cadence.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from alpha.validation.metrics import (
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe,
    calculate_sortino,
)

from best_signal.evidence import CARRY_OOS_AUDIT, REPO_ROOT
from best_signal.funding import FundingPrint, PERIODS_PER_YEAR
from best_signal.rules import AlwaysOnCarry, RuleDecision, RuleState

DEFAULT_FEE = 0.0005
DEFAULT_NOTIONAL = 10_000.0
DEFAULT_CAPITAL = 10_000.0
DEFAULT_BORROW_ANNUAL = 0.0
HOURS_PER_YEAR = 8760.0
DEFAULT_PERIOD_HOURS = 8.0
FEE_STRESS_MULTIPLIERS = (1.0, 2.0, 3.0)
SLIPPAGE_STRESS_BPS = (0.0, 1.0, 2.0, 5.0, 10.0)
RANDOM_CONTROL_SEED = 20261122
LOOKAHEAD_SAMPLE = 50
ARCHIVE_CONTROL_KEY = "always_short_perp_side_plus1"

CAVEATS = (
    "delta-flat (long spot + short perp), not delta-zero",
    "basis risk is not modelled; intraday premium excursions are understated",
    "no margin, liquidation or exchange-outage modelling",
    "borrow is charged on the short-spot leg only, at a flat annual rate",
    "a position opened at print i also collects print i's funding (one print of optimism per open)",
)


@dataclass(frozen=True)
class Candidate:
    """A signal under test: a rule factory plus the grid searched on IS only."""

    name: str
    thesis: str
    rule_factory: Callable[[dict], object]
    param_grid: list[dict] = field(default_factory=list)
    kind: str = "timing"


@dataclass
class SimulationResult:
    collected: float
    fees: float
    borrow: float
    net: float
    return_pct: float
    side_changes: int
    flips: int
    side_series: list[int]
    equity_curve: list[float]
    print_returns: list[float]
    prints: list[FundingPrint]


def _period_hours(prints: Sequence[FundingPrint], index: int) -> float:
    """Wall-clock hours the position was exposed during print ``index``."""
    if index > 0:
        gap = prints[index].ts_ms - prints[index - 1].ts_ms
        if gap > 0:
            return gap / 3_600_000.0
    if len(prints) > 1 and index < len(prints) - 1:
        gap = prints[index + 1].ts_ms - prints[index].ts_ms
        if gap > 0:
            return gap / 3_600_000.0
    return DEFAULT_PERIOD_HOURS


def _finite(value):
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def simulate_rule(
    rule,
    prints: Sequence[FundingPrint],
    fee: float = DEFAULT_FEE,
    notional: float = DEFAULT_NOTIONAL,
    capital: float = DEFAULT_CAPITAL,
    borrow_annual: float = DEFAULT_BORROW_ANNUAL,
    extra_bps: float = 0.0,
) -> SimulationResult:
    """Run ``rule`` over ``prints`` under the bot's accounting conventions."""
    prints = list(prints)
    state = rule.new_state()
    leg_rate = fee + extra_bps / 10_000.0

    held = 0
    collected = 0.0
    fees = 0.0
    borrow = 0.0
    side_changes = 0
    flips = 0
    side_series: list[int] = []
    equity_curve: list[float] = []
    print_returns: list[float] = []

    for index, current in enumerate(prints):
        decision = rule.step(prints[:index], state)
        target = int(decision.side)
        if target not in (-1, 0, 1):
            raise ValueError(f"rule returned invalid side {target}")

        fees_this_print = 0.0
        if target != held:
            side_changes += 1
            if held != 0 and target != 0:
                legs = 4
                flips += 1
            else:
                legs = 2
            fees_this_print = legs * leg_rate * notional
            fees += fees_this_print
            held = target

        funding = held * current.rate * notional
        collected += funding

        borrow_this_print = 0.0
        if held == -1:
            borrow_this_print = (
                borrow_annual * notional * _period_hours(prints, index) / HOURS_PER_YEAR
            )
            borrow += borrow_this_print

        pnl = funding - fees_this_print - borrow_this_print
        side_series.append(held)
        print_returns.append(pnl / capital)
        equity_curve.append(collected - fees - borrow)

    net = collected - fees - borrow
    return SimulationResult(
        collected=collected,
        fees=fees,
        borrow=borrow,
        net=net,
        return_pct=net / capital * 100.0,
        side_changes=side_changes,
        flips=flips,
        side_series=side_series,
        equity_curve=equity_curve,
        print_returns=print_returns,
        prints=prints,
    )


def _summary(result: SimulationResult, include_prints: bool = False) -> dict:
    returns = np.asarray(result.print_returns, dtype=float)
    if returns.size == 0:
        sharpe = sortino = max_drawdown = profit_factor = 0.0
    else:
        sharpe = calculate_sharpe(returns, periods_per_year=PERIODS_PER_YEAR)
        sortino = calculate_sortino(returns, periods_per_year=PERIODS_PER_YEAR)
        max_drawdown = calculate_max_drawdown(returns)
        profit_factor = calculate_profit_factor(returns)

    summary = {
        "collected": result.collected,
        "fees": result.fees,
        "borrow": result.borrow,
        "net": result.net,
        "return_pct": result.return_pct,
        "side_changes": result.side_changes,
        "flips": result.flips,
        "sharpe": _finite(sharpe),
        "sortino": _finite(sortino),
        "max_drawdown": _finite(max_drawdown),
        "profit_factor": _finite(profit_factor),
    }
    if include_prints:
        summary["prints"] = result.prints
        summary["side_series"] = result.side_series
    return summary


def split_prints(
    prints: Sequence[FundingPrint],
) -> dict[str, list[FundingPrint]]:
    """Split prints 60/15/25 on record count, preserving order."""
    prints = list(prints)
    total = len(prints)
    in_sample_end = int(total * 0.60)
    validation_end = in_sample_end + int(total * 0.15)
    return {
        "in_sample": prints[:in_sample_end],
        "validation": prints[in_sample_end:validation_end],
        "out_of_sample": prints[validation_end:],
    }


class _ConstantSideCarry:
    """Carry book pinned to one side, used for the no-information controls."""

    def __init__(self, side: int):
        self.side = side
        self.name = f"constant_{side:+d}_carry"

    def new_state(self) -> RuleState:
        return RuleState(side=self.side)

    def step(self, prints, state) -> RuleDecision:
        return RuleDecision(side=self.side, reason="constant_side")


class _RandomFlipCarry:
    """Carry book that flips sign at random prints, matched on flip count."""

    name = "random_timing_matched_flips"

    def __init__(self, flip_indices: Sequence[int]):
        self.flip_indices = set(flip_indices)
        self.side = 1
        self.flips = 0

    def new_state(self) -> RuleState:
        return RuleState(side=1)

    def step(self, prints, state) -> RuleDecision:
        if len(prints) in self.flip_indices:
            self.side = -self.side
            self.flips += 1
        state.side = self.side
        return RuleDecision(side=self.side, reason="random_flip")


def _random_flip_indices(total: int, flips: int) -> list[int]:
    flips = max(0, min(int(flips), max(0, total - 1)))
    if flips == 0 or total < 2:
        return []
    rng = random.Random(RANDOM_CONTROL_SEED)
    return sorted(rng.sample(range(1, total), flips))


def no_information_controls(
    prints: Sequence[FundingPrint], matched_flips: int = 0
) -> dict[str, dict]:
    """Controls that carry no timing information, scored on the same path."""
    prints = list(prints)
    receive = simulate_rule(AlwaysOnCarry(), prints)
    pay = simulate_rule(_ConstantSideCarry(-1), prints)
    flip_indices = _random_flip_indices(len(prints), matched_flips)
    random_rule = _RandomFlipCarry(flip_indices)
    random_book = simulate_rule(random_rule, prints)

    return {
        "always_receive": _summary(receive),
        "always_pay": _summary(pay),
        "random_timing_matched_flips": {
            **_summary(random_book),
            "flips": random_rule.flips,
            "flip_indices": flip_indices,
        },
    }


def _verify_no_lookahead(
    rule_factory: Callable[[], object],
    prints: Sequence[FundingPrint],
    side_series: Sequence[int],
    sample: int = LOOKAHEAD_SAMPLE,
) -> bool:
    """Replay with every future print sign-flipped; the past must not move."""
    prints = list(prints)
    if not prints:
        return True
    step = max(1, len(prints) // max(1, sample))
    indices = list(range(0, len(prints), step))[:sample]
    for index in indices:
        perturbed = list(prints[:index]) + [
            FundingPrint(ts_ms=print_.ts_ms, rate=-print_.rate)
            for print_ in prints[index:]
        ]
        replay = simulate_rule(rule_factory(), perturbed)
        if list(replay.side_series[: index + 1]) != list(side_series[: index + 1]):
            return False
    return True


def _thirds(items: list) -> list[list]:
    if not items:
        return [[], [], []]
    size = len(items) / 3.0
    first = int(size)
    second = int(size * 2)
    return [items[:first], items[first:second], items[second:]]


def validate_candidate(candidate: Candidate, prints: Sequence[FundingPrint]) -> dict:
    """Run the full pre-registered protocol for one candidate."""
    prints = list(prints)
    splits = split_prints(prints)

    ranking = []
    for params in candidate.param_grid or [{}]:
        params = dict(params)
        result = simulate_rule(candidate.rule_factory(dict(params)), splits["in_sample"])
        ranking.append(
            {
                "params": params,
                "net": result.net,
                "return_pct": result.return_pct,
                "side_changes": result.side_changes,
                "flips": result.flips,
                "split": "in_sample",
            }
        )
    ranking.sort(key=lambda entry: (-entry["net"], repr(entry["params"])))
    selected = ranking[0]["params"] if ranking else {}

    def frozen_rule():
        return candidate.rule_factory(dict(selected))

    frozen = {}
    for split_name, split in splits.items():
        result = simulate_rule(frozen_rule(), split)
        frozen[split_name] = _summary(result, include_prints=True)
    frozen["params"] = selected

    oos_prints = splits["out_of_sample"]
    oos_result = simulate_rule(frozen_rule(), oos_prints)
    controls = no_information_controls(oos_prints, matched_flips=oos_result.flips)

    walk_forward = {}
    walk_forward_stats = {}
    for index, chunk in enumerate(_thirds(oos_prints), start=1):
        walk_forward[f"third_{index}"] = chunk
        walk_forward_stats[f"third_{index}"] = _summary(simulate_rule(frozen_rule(), chunk))

    fee_stress = {}
    for multiplier in FEE_STRESS_MULTIPLIERS:
        result = simulate_rule(frozen_rule(), oos_prints, fee=DEFAULT_FEE * multiplier)
        fee_stress[f"{multiplier:g}x"] = _summary(result)

    slippage_stress = {}
    for bps in SLIPPAGE_STRESS_BPS:
        result = simulate_rule(frozen_rule(), oos_prints, extra_bps=bps)
        slippage_stress[f"{bps:g}bps"] = _summary(result)

    best_constant = max(
        controls["always_receive"]["net"], controls["always_pay"]["net"]
    )
    is_net = frozen["in_sample"]["net"]
    oos_net = frozen["out_of_sample"]["net"]
    strict = candidate.kind == "timing"
    structural = candidate.kind == "structural"

    checks = {
        "in_sample_selection_is_is_only": all(
            entry["split"] == "in_sample" for entry in ranking
        ),
        "in_sample_net_positive": bool(is_net > 0),
        "validation_net_positive": bool(frozen["validation"]["net"] > 0),
        "out_of_sample_net_positive": bool(oos_net > 0),
        "walk_forward_thirds_all_positive": bool(
            all(stats["net"] > 0 for stats in walk_forward_stats.values())
        ),
        "beats_always_pay": bool(oos_net > controls["always_pay"]["net"]),
        "survives_fee_stress_3x": bool(fee_stress["3x"]["net"] > 0),
        "survives_slippage_stress_10bps": bool(slippage_stress["10bps"]["net"] > 0),
        "no_lookahead": bool(
            _verify_no_lookahead(frozen_rule, oos_prints, oos_result.side_series)
        ),
    }

    if structural:
        verdict_note = (
            "structural carry: the candidate is the constant-side book, so the "
            "always-receive control is the same book and the timing comparison "
            "does not apply"
        )
    else:
        verdict_note = ""
        checks["beats_best_constant_side"] = bool(
            oos_net > best_constant if strict else oos_net >= best_constant
        )
        checks["beats_random_timing"] = bool(
            oos_net > controls["random_timing_matched_flips"]["net"]
            if strict
            else oos_net >= controls["random_timing_matched_flips"]["net"]
        )

    failed = [name for name, passed in checks.items() if not passed]
    if strict and not checks["beats_best_constant_side"]:
        verdict = (
            "NO SKILL - timing overlay does not beat the constant-side carry book"
        )
    elif structural and not failed:
        verdict = "STRUCTURAL CARRY - out-of-sample positive; not a timing edge"
    elif not failed:
        verdict = "VALIDATED OUT-OF-SAMPLE"
    elif checks["in_sample_net_positive"] and not checks["out_of_sample_net_positive"]:
        verdict = "IN-SAMPLE ONLY - edge did not survive the out-of-sample window"
    else:
        verdict = "NOT VALIDATED - " + ", ".join(failed)

    return {
        "candidate": candidate.name,
        "kind": candidate.kind,
        "thesis": candidate.thesis,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "failed_checks": failed,
        "params_selected": selected,
        "is_ranking": ranking,
        "frozen": frozen,
        "controls": controls,
        "oos_walk_forward": walk_forward,
        "oos_walk_forward_stats": walk_forward_stats,
        "oos_fee_stress": fee_stress,
        "oos_slippage_stress": slippage_stress,
        "checks": checks,
        "caveats": list(CAVEATS),
        "assumptions": {
            "fee_per_leg": DEFAULT_FEE,
            "notional": DEFAULT_NOTIONAL,
            "capital": DEFAULT_CAPITAL,
            "borrow_annual": DEFAULT_BORROW_ANNUAL,
            "periods_per_year": PERIODS_PER_YEAR,
            "execution_lag_prints": 1,
            "split": "60/15/25 on record count",
        },
        "prints_total": len(prints),
    }


def reconcile_archive_window(
    prints: Sequence[FundingPrint],
    window_start_ms: int,
    window_end_ms: int,
    archived_net: float,
    archived_collected: float | None = None,
    archived_records: int | None = None,
    fee: float = DEFAULT_FEE,
    notional: float = DEFAULT_NOTIONAL,
) -> dict:
    """Re-run the carry book on the archived window and compare it to the archive.

    The archived audit ran a shorter window and charged no entry cost, so the
    local re-run is expected to match the archived *collected* figure exactly
    and to sit one entry fee below the archived net.
    """
    archived_collected_value = (
        archived_net if archived_collected is None else archived_collected
    )
    window = [
        print_
        for print_ in prints
        if window_start_ms <= print_.ts_ms <= window_end_ms
    ]
    row = {
        "window": {"first_ts_ms": window_start_ms, "last_ts_ms": window_end_ms},
        "local_records": len(window),
        "archived_records": archived_records,
        "archived_oos_net": archived_net,
        "archived_oos_collected": archived_collected_value,
    }
    if not window:
        row.update(
            {
                "status": "no_local_data",
                "oos_prints": 0,
                "local_oos_collected": 0.0,
                "local_oos_net": 0.0,
                "local_oos_fees": 0.0,
                "collected_matches_archive": False,
                "net_matches_archive": False,
                "explanation": (
                    "no local funding prints fall inside the archived window"
                ),
            }
        )
        return row

    oos = split_prints(window)["out_of_sample"]
    result = simulate_rule(AlwaysOnCarry(), oos, fee=fee, notional=notional)
    collected_matches = abs(result.collected - archived_collected_value) <= 0.01
    row.update(
        {
            "status": "reproduced" if collected_matches else "mismatch",
            "oos_prints": len(oos),
            "local_oos_collected": result.collected,
            "local_oos_net": result.net,
            "local_oos_fees": result.fees,
            "collected_matches_archive": collected_matches,
            "net_matches_archive": abs(result.net - archived_net) <= 0.01,
            "explanation": (
                "the archived audit charged no entry cost on the initial open; this "
                "harness charges 2 taker legs, so the local net sits one entry fee "
                "below the archived net"
            ),
        }
    )
    return row


def reconcile_archive_audit(
    prints_by_symbol: Mapping[str, Sequence[FundingPrint]],
    audit_path: Path | str = REPO_ROOT / CARRY_OOS_AUDIT,
    fee: float = DEFAULT_FEE,
    notional: float = DEFAULT_NOTIONAL,
) -> dict[str, dict]:
    """Reconcile the local harness against the archived carry audit, per symbol.

    A missing audit, a symbol the archive never audited, or local data that
    does not reach the archived window is reported as such. Nothing here is
    allowed to fail silently.
    """
    path = Path(audit_path)
    if not path.is_file():
        return {
            symbol: {
                "status": "audit_unavailable",
                "local_records": 0,
                "oos_prints": 0,
                "local_oos_collected": 0.0,
                "local_oos_net": 0.0,
                "local_oos_fees": 0.0,
                "collected_matches_archive": False,
                "net_matches_archive": False,
                "explanation": f"archived audit {path} is not on disk",
            }
            for symbol in prints_by_symbol
        }

    audit = json.loads(path.read_text())
    archived_symbols = audit.get("symbols", {})
    rows: dict[str, dict] = {}
    for symbol, prints in prints_by_symbol.items():
        archived = archived_symbols.get(symbol)
        if archived is None:
            rows[symbol] = {
                "status": "not_in_archive",
                "local_records": len(prints),
                "oos_prints": 0,
                "local_oos_collected": 0.0,
                "local_oos_net": 0.0,
                "local_oos_fees": 0.0,
                "collected_matches_archive": False,
                "net_matches_archive": False,
                "explanation": f"the archived audit has no {symbol} record",
            }
            continue
        control = archived["no_information_controls"]["out_of_sample"][
            ARCHIVE_CONTROL_KEY
        ]
        rows[symbol] = reconcile_archive_window(
            prints,
            archived["first_ts"],
            archived["last_ts"],
            archived_net=control["net"],
            archived_collected=control["collected"],
            archived_records=archived["records"],
            fee=fee,
            notional=notional,
        )
    return rows
