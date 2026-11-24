"""
Unified signal screener.

Screens candidate signals through the quality gates in
alpha.factors.quality_validator (IC mean, IR, turnover, decay, sector
neutrality, crowding, drawdown) using SignalQualityValidator and
FactorScreeningPipeline, and writes a ranked list of passing signals as JSON
and markdown artifacts.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from alpha.factors.quality_validator import (
    FactorQualityReport,
    FactorScreeningPipeline,
    QualityThresholds,
    SignalQualityValidator,
)


@dataclass
class CandidateSignal:
    """One candidate signal plus the metrics the quality gates need."""

    name: str
    ic_mean: float = 0.05
    ic_std: float = 0.02
    ic_ir: float = 2.5
    ic_t_stat: float = 10.0
    ic_p_value: float = 0.001
    positive_ic_ratio: float = 0.6
    max_drawdown: float = -0.03
    decay: dict = field(default_factory=lambda: {1: 0.05, 5: 0.04, 10: 0.02})
    turnover: float = 0.2
    sector_neutral_ic: float = 0.04
    n_observations: int = 200
    crowding_score: float = 10.0
    # Signal metadata carried through from the source (e.g. best-signal bot).
    symbol: str = ""
    action: str = ""
    side: int = 0
    notional: float = 0.0
    reason: str = ""
    candidate: str = ""
    price: float = 0.0
    generated_at: str = ""
    source: str = ""
    thesis: str = ""


@dataclass
class ScreenerConfig:
    thresholds: Optional[QualityThresholds] = None
    min_pass_rate: float = 0.8


class SignalScreener:
    """Screen candidate signals through factor quality gates."""

    def __init__(self, config: Optional[ScreenerConfig] = None):
        self.config = config or ScreenerConfig()
        self.pipeline = FactorScreeningPipeline(
            SignalQualityValidator(self.config.thresholds),
            min_pass_rate=self.config.min_pass_rate,
        )

    def _factor_result(self, candidate) -> dict:
        if isinstance(candidate, CandidateSignal):
            return {
                "ic_mean": candidate.ic_mean,
                "ic_std": candidate.ic_std,
                "ic_ir": candidate.ic_ir,
                "ic_t_stat": candidate.ic_t_stat,
                "ic_p_value": candidate.ic_p_value,
                "positive_ic_ratio": candidate.positive_ic_ratio,
                "max_drawdown": candidate.max_drawdown,
                "decay": candidate.decay,
                "turnover": candidate.turnover,
                "sector_neutral_ic": candidate.sector_neutral_ic,
                "n_observations": candidate.n_observations,
            }
        return dict(candidate)

    def _crowding(self, candidates) -> dict:
        return {c.name: float(c.crowding_score) for c in candidates}

    def screen(self, candidates):
        """Run every candidate through the quality gates.

        Returns (passed_names, failed_names, reports).
        """
        factor_results = {c.name: self._factor_result(c) for c in candidates}
        return self.pipeline.screen_factors(
            factor_results, crowding_scores=self._crowding(candidates)
        )

    def rank(self, candidates) -> pd.DataFrame:
        """Rank candidates by quality score, best first."""
        factor_results = {c.name: self._factor_result(c) for c in candidates}
        return self.pipeline.get_factor_ranking(
            factor_results, crowding_scores=self._crowding(candidates)
        )

    def reports(self, candidates) -> dict[str, FactorQualityReport]:
        factor_results = {c.name: self._factor_result(c) for c in candidates}
        return self.pipeline.report_generator.batch_validate(
            factor_results, crowding_scores=self._crowding(candidates)
        )

    def write_artifacts(self, candidates, out_dir, prefix="signal_screener"):
        """Screen candidates and write JSON + markdown artifacts. Returns paths."""
        passed, failed, reports = self.screen(candidates)
        ranking = self.rank(candidates)

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        results = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidates_screened": len(candidates),
            "passed": passed,
            "failed": failed,
            "pass_rate": len(passed) / len(candidates) if candidates else 0.0,
            "reports": {name: report.to_dict() for name, report in reports.items()},
            "ranking": _sanitize(ranking.to_dict("records")),
        }

        json_path = out / f"{prefix}_results.json"
        json_path.write_text(json.dumps(results, indent=2) + "\n")

        markdown_path = out / f"{prefix}_report.md"
        markdown_path.write_text(
            self._render_markdown(passed, failed, reports, ranking)
        )

        return {
            "json": json_path,
            "markdown": markdown_path,
            "passed": passed,
            "failed": failed,
            "reports": reports,
            "ranking": ranking,
        }

    def _render_markdown(self, passed, failed, reports, ranking) -> str:
        lines = ["# Signal Screener Report", ""]
        lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"- Candidates screened: {len(passed) + len(failed)}")
        lines.append(f"- Passed: {len(passed)}")
        lines.append(f"- Failed: {len(failed)}")
        total = len(passed) + len(failed)
        if total:
            lines.append(f"- Pass rate: {len(passed) / total:.1%}")
        lines.append("")

        lines.append("## Passing signals")
        lines.append("")
        if not passed:
            lines.append("No signals passed the quality gates.")
            lines.append("")
        else:
            lines.append(
                "| rank | name | quality_score | ic_mean | ic_ir | turnover | decay_ratio | positive_ic_ratio | max_drawdown |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|")
            for rank, name in enumerate(passed, start=1):
                report = reports[name]
                checks = {c.check.value: c for c in report.checks}
                score = report.summary["passed"] / max(report.summary["total_checks"], 1)
                lines.append(
                    "| {rank} | {name} | {score:.2f} | {ic_mean} | {ic_ir} | {turnover} | {decay} | {pos} | {dd} |".format(
                        rank=rank,
                        name=name,
                        score=score,
                        ic_mean=_check_value(checks.get("ic_mean")),
                        ic_ir=_check_value(checks.get("ic_ir")),
                        turnover=_check_value(checks.get("turnover")),
                        decay=_check_value(checks.get("decay")),
                        pos=_check_value(checks.get("positive_ic_ratio")),
                        dd=_check_value(checks.get("drawdown")),
                    )
                )
            lines.append("")

        lines.append("## Failed signals")
        lines.append("")
        if not failed:
            lines.append("No signals failed the quality gates.")
            lines.append("")
        else:
            lines.append("| name | quality_score | failed checks |")
            lines.append("|---|---|---|")
            for name in failed:
                report = reports[name]
                failed_checks = [
                    f"{c.check.value} ({c.severity})"
                    for c in report.checks
                    if not c.passed
                ]
                score = report.summary["passed"] / max(report.summary["total_checks"], 1)
                lines.append(
                    "| {name} | {score:.2f} | {checks} |".format(
                        name=name,
                        score=score,
                        checks=", ".join(failed_checks) or "none",
                    )
                )
            lines.append("")

        lines.append("## Quality check details")
        lines.append("")
        for name in passed + failed:
            report = reports[name]
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"- Overall: {'PASS' if report.overall_pass else 'FAIL'}")
            for c in report.checks:
                status = "PASS" if c.passed else ("FAIL" if c.severity == "fail" else "WARN")
                lines.append(f"- {c.check.value}: {status} - {c.message}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def _check_value(check) -> str:
    if check is None:
        return "n/a"
    if isinstance(check.value, float):
        return f"{check.value:.4f}"
    return str(check.value)


def _sanitize(value):
    """Coerce numpy/pandas scalars into plain JSON types."""
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return _sanitize(value.tolist())
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def load_best_signal_signals(path) -> list[CandidateSignal]:
    """Read the best-signal bot's signal artifact and convert to candidates.

    This is the integration point with the best-signal bot evidence registry:
    each emitted signal (best_signal_signals.json) becomes a candidate the
    screener can run through the quality gates once quality metrics are
    supplied.
    """
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = [data]
    candidate_fields = {f.name for f in fields(CandidateSignal)}
    candidates = []
    for entry in data:
        data = {k: v for k, v in entry.items() if k in candidate_fields}
        candidates.append(CandidateSignal(**data))
    return candidates


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha.factors.signal_screener",
        description=(
            "Screen candidate signals through factor quality gates and write "
            "a ranked list of passing signals as JSON and markdown artifacts."
        ),
    )
    parser.add_argument(
        "--candidates", required=True, help="JSON file: list of candidate dicts or dict of name -> candidate dict"
    )
    parser.add_argument(
        "--out-dir", default="reports/signal_screener", help="Output directory for artifacts"
    )
    parser.add_argument(
        "--prefix", default="signal_screener", help="Artifact filename prefix"
    )
    parser.add_argument("--ic-mean-min", type=float, default=None)
    parser.add_argument("--ic-ir-min", type=float, default=None)
    parser.add_argument("--turnover-max", type=float, default=None)
    parser.add_argument("--decay-max", type=float, default=None)
    return parser


def main(argv=None) -> int:
    """Command-line entry point. Returns a process exit code."""
    args = _build_parser().parse_args(argv)

    thresholds = QualityThresholds()
    if args.ic_mean_min is not None:
        thresholds.ic_mean_min = args.ic_mean_min
    if args.ic_ir_min is not None:
        thresholds.ic_ir_min = args.ic_ir_min
    if args.turnover_max is not None:
        thresholds.turnover_max = args.turnover_max
    if args.decay_max is not None:
        thresholds.decay_max = args.decay_max

    screener = SignalScreener(ScreenerConfig(thresholds=thresholds))
    data = json.loads(Path(args.candidates).read_text())
    if isinstance(data, dict):
        items = [{"name": name, **metrics} for name, metrics in data.items()]
    else:
        items = list(data)
    candidate_fields = {f.name for f in fields(CandidateSignal)}
    candidates = [
        CandidateSignal(
            name=entry.get("name") or entry.get("symbol") or "unknown",
            **{k: v for k, v in entry.items() if k in candidate_fields and k != "name"},
        )
        for entry in items
    ]

    result = screener.write_artifacts(candidates, args.out_dir, prefix=args.prefix)

    print(
        f"signal screener: {len(result['passed'])}/{len(candidates)} candidates passed"
    )
    print(f"  json: {result['json']}")
    print(f"  markdown: {result['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
