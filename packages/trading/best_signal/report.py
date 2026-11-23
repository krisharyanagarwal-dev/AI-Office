"""Report writer for the best-signal bot.

The report is the artifact a human reads to judge what the bot did and why:
the evidence ranking, the selected candidate, the paper targets, the
out-of-sample verdicts and the caveats that keep the result from being read
as a live mandate.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from best_signal.evidence import (
    CandidateRecord,
    candidate_gates,
    ranking_table,
    select_tradable,
)
from best_signal.position import PaperPosition
from best_signal.validate import CAVEATS

REPORT_JSON_NAME = "best_signal_report.json"
REPORT_MARKDOWN_NAME = "best_signal_report.md"

LIVE_FALSE = False
MODE_PAPER = "PAPER"


def jsonable(value):
    """Coerce dataclasses and numpy scalars into plain JSON types."""
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return jsonable(tolist())
    item = getattr(value, "item", None)
    if callable(item):
        return jsonable(item())
    return str(value)


def _position_dict(position) -> dict:
    if isinstance(position, PaperPosition):
        return position.to_dict()
    to_dict = getattr(position, "to_dict", None)
    if callable(to_dict):
        return jsonable(to_dict())
    return jsonable(position)


def _trim_validation(result: dict) -> dict:
    """Replace the per-print arrays with their counts so the report stays readable."""
    trimmed = {}
    for key, value in result.items():
        if key != "frozen" or not isinstance(value, dict):
            trimmed[key] = value
            continue
        frozen = {}
        for split, summary in value.items():
            if not isinstance(summary, dict):
                frozen[split] = summary
                continue
            summary = dict(summary)
            prints = summary.pop("prints", None)
            summary.pop("side_series", None)
            if prints is not None:
                summary["prints_count"] = len(prints)
            frozen[split] = summary
        trimmed[key] = frozen
    return trimmed


def _candidate_dict(record: CandidateRecord) -> dict:
    return {
        "name": record.name,
        "thesis": record.thesis,
        "kind": record.kind,
        "status": record.status,
        "reasons": list(record.reasons),
        "citations": [
            {"path": citation.path, "claim": citation.claim}
            for citation in record.citations
        ],
        "metrics": dict(record.metrics),
        "gates": candidate_gates(record),
        "rule_key": record.rule_key,
    }


def build_report(
    records: Sequence[CandidateRecord],
    positions: Sequence,
    validations: dict | None = None,
    generated_at: str | None = None,
    data_summary: dict | None = None,
    reconciliation: dict | None = None,
) -> dict:
    """Assemble the JSON-serialisable report for one bot run."""
    records = list(records)
    selected = select_tradable(records)
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "mode": MODE_PAPER,
        "live": LIVE_FALSE,
        "selected_candidate": _candidate_dict(selected) if selected else None,
        "ranking": ranking_table(records),
        "positions": [_position_dict(position) for position in positions],
        "validation": {
            symbol: _trim_validation(jsonable(result))
            for symbol, result in (validations or {}).items()
        },
        "reconciliation": jsonable(reconciliation) if reconciliation is not None else None,
        "caveats": list(CAVEATS),
        "data_summary": jsonable(data_summary) if data_summary is not None else None,
    }


def _render_positions(lines: list[str], positions: list[dict]) -> None:
    lines.append("## Paper positions")
    lines.append("")
    if not positions:
        lines.append("No positions were emitted.")
        lines.append("")
        return
    lines.append("| symbol | action | side | notional | reason | candidate | live |")
    lines.append("|---|---|---|---|---|---|---|")
    for position in positions:
        lines.append(
            "| {symbol} | {action} | {side} | {notional} | {reason} | {candidate} | {live} |".format(
                symbol=position.get("symbol", ""),
                action=position.get("action", ""),
                side=position.get("side", 0),
                notional=position.get("notional", 0.0),
                reason=position.get("reason", ""),
                candidate=position.get("candidate", ""),
                live=str(position.get("live", LIVE_FALSE)).lower(),
            )
        )
    lines.append("")


def _render_ranking(lines: list[str], ranking: list[dict]) -> None:
    lines.append("## Evidence ranking")
    lines.append("")
    if not ranking:
        lines.append("No candidates were registered.")
        lines.append("")
        return
    lines.append("| rank | candidate | kind | status | thesis |")
    lines.append("|---|---|---|---|---|")
    for row in ranking:
        lines.append(
            "| {rank} | {name} | {kind} | {status} | {thesis} |".format(
                rank=row.get("rank", ""),
                name=row.get("name", ""),
                kind=row.get("kind", ""),
                status=row.get("status", ""),
                thesis=row.get("thesis", ""),
            )
        )
    lines.append("")
    for row in ranking:
        lines.append(f"### {row.get('name', '')}")
        lines.append("")
        for reason in row.get("reasons", []):
            lines.append(f"- Reason: {reason}")
        for citation in row.get("citations", []):
            lines.append(
                f"- Citation: `{citation.get('path', '')}` - {citation.get('claim', '')}"
            )
        metrics = row.get("metrics") or {}
        if metrics:
            rendered = ", ".join(f"{key}={value}" for key, value in metrics.items())
            lines.append(f"- Metrics: {rendered}")
        gates = row.get("gates") or {}
        if gates:
            rendered = ", ".join(f"{key}={value}" for key, value in gates.items())
            lines.append(f"- Gates: {rendered}")
        lines.append("")


def _render_validation(lines: list[str], validation: dict) -> None:
    lines.append("## Out-of-sample validation")
    lines.append("")
    if not validation:
        lines.append("No validation run was attached to this report.")
        lines.append("")
        return
    lines.append("| symbol | verdict | failed checks |")
    lines.append("|---|---|---|")
    for symbol, result in validation.items():
        failed = ", ".join(result.get("failed_checks", []) or []) or "none"
        lines.append(f"| {symbol} | {result.get('verdict', '')} | {failed} |")
    lines.append("")
    for symbol, result in validation.items():
        lines.append(f"### {symbol}")
        lines.append("")
        frozen = result.get("frozen") or {}
        oos = frozen.get("out_of_sample") or {}
        if oos:
            lines.append(
                "- Out-of-sample net: {net:.4f} over {prints} prints".format(
                    net=float(oos.get("net", 0.0)),
                    prints=int(oos.get("prints_count", 0) or 0),
                )
            )
        for caveat in result.get("caveats", []) or []:
            lines.append(f"- Caveat: {caveat}")
        lines.append("")


def _render_reconciliation(lines: list[str], reconciliation: dict | None) -> None:
    lines.append("## Archived-audit reconciliation")
    lines.append("")
    if not reconciliation:
        lines.append("No reconciliation against the archived audit was attached.")
        lines.append("")
        return
    lines.append(
        "The registry cites numbers produced by an archived audit on a different "
        "window. This block re-runs the local harness on that exact window."
    )
    lines.append("")
    lines.append(
        "| symbol | status | archived OOS net | local OOS net | local OOS fees | "
        "collected matches |"
    )
    lines.append("|---|---|---|---|---|---|")
    for symbol, row in reconciliation.items():
        lines.append(
            "| {symbol} | {status} | {archived} | {local} | {fees} | {matches} |".format(
                symbol=symbol,
                status=row.get("status", ""),
                archived=float(row.get("archived_oos_net", 0.0) or 0.0),
                local=float(row.get("local_oos_net", 0.0) or 0.0),
                fees=float(row.get("local_oos_fees", 0.0) or 0.0),
                matches=str(row.get("collected_matches_archive", False)).lower(),
            )
        )
    lines.append("")
    for symbol, row in reconciliation.items():
        explanation = row.get("explanation")
        if explanation:
            lines.append(f"- {symbol}: {explanation}")
    lines.append("")


def render_markdown(report: dict) -> str:
    """Render the report as markdown for a human reader."""
    lines = ["# Best-signal bot report", ""]
    lines.append(f"- Generated: {report.get('generated_at', 'unknown')}")
    lines.append(
        f"- Mode: {report.get('mode', MODE_PAPER)} "
        f"(live={str(report.get('live', LIVE_FALSE)).lower()})"
    )
    lines.append(
        "- This bot never places an order. Every position below is a paper target."
    )
    lines.append(
        "- A failed gate produces an explicit NO_TRADE position, never a silently "
        "resized one."
    )
    lines.append("")

    lines.append("## Selected candidate")
    lines.append("")
    selected = report.get("selected_candidate")
    if not selected:
        lines.append(
            "No candidate passed the evidence gate, so the bot stands down and "
            "emits NO_TRADE."
        )
    else:
        lines.append(f"### {selected.get('name', '')}")
        lines.append("")
        lines.append(f"- Thesis: {selected.get('thesis', '')}")
        lines.append(
            f"- Kind: {selected.get('kind', '')} | Status: {selected.get('status', '')}"
        )
        for reason in selected.get("reasons", []):
            lines.append(f"- Reason: {reason}")
        for citation in selected.get("citations", []):
            lines.append(
                f"- Citation: `{citation.get('path', '')}` - {citation.get('claim', '')}"
            )
    lines.append("")

    _render_positions(lines, report.get("positions", []))
    _render_ranking(lines, report.get("ranking", []))
    _render_validation(lines, report.get("validation", {}))
    _render_reconciliation(lines, report.get("reconciliation"))

    lines.append("## Caveats")
    lines.append("")
    for caveat in report.get("caveats", []):
        lines.append(f"- {caveat}")
    lines.append("")

    data_summary = report.get("data_summary")
    if data_summary:
        lines.append("## Data summary")
        lines.append("")
        for key, value in data_summary.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_report(report: dict, out_dir) -> dict:
    """Write the JSON and markdown artifacts and return their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / REPORT_JSON_NAME
    markdown_path = out / REPORT_MARKDOWN_NAME
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    markdown_path.write_text(render_markdown(report))
    return {"json": json_path, "markdown": markdown_path}
