"""Evidence registry for the best-signal bot.

Every candidate carries the artifacts that justify its verdict and the exact
numbers the archived work recorded. A citation that does not resolve on disk
is a failed gate, not a footnote: ``verify_citations`` turns it into a
blocking check before any position is emitted.

The registry is deliberately static. It records what the archived
out-of-sample work already concluded so the bot never re-litigates a
rejected hypothesis on live data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES_ROOT = Path(__file__).resolve().parents[2]

ARCHIVE = "packages/_archive/all-files"
CARRY_OOS_AUDIT = f"{ARCHIVE}/json/carry_oos_audit.json"
TOURNAMENT_SOURCE = f"{ARCHIVE}/py/oa_tournament.py"
EDGE_PROBE_REPORT = f"{ARCHIVE}/md/FINAL_REPORT.md"
LOWTURN_BACKTEST = f"{ARCHIVE}/py/backtest_lowturn.py"
LOWTURN_LIVE = f"{ARCHIVE}/py/ml_lowturn_live.py"

STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED = "REJECTED"
STATUS_RESEARCH = "RESEARCH"

_STATUS_ORDER = {STATUS_ACCEPTED: 0, STATUS_RESEARCH: 1, STATUS_REJECTED: 2}
_KIND_ORDER = {"structural": 0, "timing": 1, "research": 2}


@dataclass(frozen=True)
class Citation:
    """A repo-relative artifact that backs the recorded verdict."""

    path: str
    claim: str


@dataclass(frozen=True)
class CandidateRecord:
    """One candidate signal and the evidence that settles it."""

    name: str
    thesis: str
    kind: str
    status: str
    reasons: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    metrics: dict = field(default_factory=dict)
    rule_key: str = ""


def default_registry() -> list[CandidateRecord]:
    """The candidate set as the archived out-of-sample evidence settles it."""
    return [
        CandidateRecord(
            name="always_on_carry",
            thesis=(
                "Positive funding is a structural carry: long spot and short perp "
                "collect funding at every native 8h print without forecasting "
                "which side will pay."
            ),
            kind="structural",
            status=STATUS_ACCEPTED,
            reasons=(
                "the archived audit's constant-side control beats every timing "
                "overlay on both symbols out of sample",
                "0 flips means no flip cost and no turnover drag",
                "the production rule oa_tournament.update_carry already collects "
                "the funding without flipping",
            ),
            citations=(
                Citation(
                    CARRY_OOS_AUDIT,
                    "always-receive control book: BTC out-of-sample net 350.30, "
                    "ETH out-of-sample net 253.54, 0 flips, 0.0% max drawdown",
                ),
                Citation(
                    TOURNAMENT_SOURCE,
                    "update_carry: 'One carry-book update: collect funding. "
                    "NEVER FLIP.'",
                ),
            ),
            metrics={
                "btc_oos_net": 350.30,
                "eth_oos_net": 253.54,
                "flips": 0,
                "oos_max_drawdown_pct": 0.0,
                "oos_prints_per_symbol": 1125,
            },
            rule_key="always_on_carry",
        ),
        CandidateRecord(
            name="regime_filtered_carry",
            thesis=(
                "Stand down when trailing annualized funding turns negative and "
                "re-enter once it clears the threshold."
            ),
            kind="timing",
            status=STATUS_RESEARCH,
            reasons=(
                "built in this repo as a candidate overlay; it has no archived "
                "out-of-sample evidence of its own yet",
                "it may only be promoted if it beats the constant-side book in "
                "the frozen out-of-sample harness",
            ),
            citations=(
                Citation(
                    CARRY_OOS_AUDIT,
                    "the constant-side control it has to beat: BTC out-of-sample "
                    "net 350.30, ETH out-of-sample net 253.54",
                ),
            ),
            metrics={},
            rule_key="regime_filtered_carry",
        ),
        CandidateRecord(
            name="ml_lowturn_ridge_20d",
            thesis=(
                "Low-turnover Ridge ensemble on 20-day forward returns, "
                "block-IC top-10 selection, causal vol-targeting."
            ),
            kind="research",
            status=STATUS_RESEARCH,
            reasons=(
                "the source calls it a paper leg with roughly 1 sigma walk-forward "
                "significance (annualized t 0.90/1.11), not a proven strategy",
                "H=20 daily forward labels with a 20-day rebalance make the "
                "training samples dependent, and block-IC uses only 6 blocks",
                "the model inputs (data, signals, reduced-universe correlation "
                "tables) are absent in this mirror, so the claim cannot be "
                "re-validated here",
            ),
            citations=(
                Citation(
                    LOWTURN_LIVE,
                    "'this is a PAPER leg built to accumulate live out-of-sample "
                    "evidence, not a proven strategy' (walk-forward significance "
                    "~1 sigma, annualized t 0.90/1.11)",
                ),
                Citation(
                    LOWTURN_BACKTEST,
                    "H, REB = 20, 20: forward-20d labels on daily samples with a "
                    "6-block block-IC selection",
                ),
            ),
            metrics={},
            rule_key="",
        ),
        CandidateRecord(
            name="persistence_flip_carry",
            thesis=(
                "Flip to the funding-receiving side after 48h of continuous "
                "adverse funding above 5e-05."
            ),
            kind="timing",
            status=STATUS_REJECTED,
            reasons=(
                "archived verdict on both symbols: NO SKILL - a constant-side "
                "book beats the rule; edge is sample funding drift, not timing",
                "the beats_always_short_no_skill check is False on BTCUSDT and "
                "ETHUSDT out of sample",
                "the constant-side book earns 350.30 (BTC OOS) / 253.54 (ETH OOS); "
                "the deployed 48h/5e-05 flip config earns 300.46 / 270.23 after "
                "flip fees",
                "flipping on every print loses 897.80 (BTC OOS) / 1015.44 "
                "(ETH OOS) to leg costs",
            ),
            citations=(
                Citation(
                    CARRY_OOS_AUDIT,
                    "per-symbol verdict 'NO SKILL - a constant-side book beats the "
                    "rule; edge is sample funding drift, not timing'; naive churn "
                    "baseline out-of-sample net -897.80 (BTC) / -1015.44 (ETH)",
                ),
                Citation(
                    TOURNAMENT_SOURCE,
                    "the production carry update never flips; the archived audit "
                    "found the flip rules had no timing skill",
                ),
            ),
            metrics={
                "btc_constant_side_oos_net": 350.30,
                "eth_constant_side_oos_net": 253.54,
                "btc_deployed_oos_net": 300.46,
                "eth_deployed_oos_net": 270.23,
                "btc_churn_oos_net": -897.80,
                "eth_churn_oos_net": -1015.44,
            },
            rule_key="persistence_flip_carry",
        ),
        CandidateRecord(
            name="edge_probe_1h4h",
            thesis=(
                "1h and 4h RSI mean-reversion gated by an SMA200 trend filter "
                "under a weekly turnover budget."
            ),
            kind="timing",
            status=STATUS_REJECTED,
            reasons=(
                "archived report: 'No validated edge was found. Both locked "
                "configurations are REJECTED.'",
                "1h gross expectancy flipped from +22.95 bp in train to -3.88 bp "
                "out of sample, a clean in-sample overfit",
                "the 4h configuration failed generalisation: 3/5 symbols, 3/5 "
                "folds, and one fold contributed 143% of all net profit",
                "the confirmatory 10-symbol test passed 0 of 7 criteria and the "
                "4h gate finding was withdrawn",
            ),
            citations=(
                Citation(
                    EDGE_PROBE_REPORT,
                    "'No validated edge was found. Both locked configurations are "
                    "REJECTED.' plus the addendum withdrawing the 4h gate finding",
                ),
            ),
            metrics={},
            rule_key="",
        ),
    ]


def verify_citations(records, root: Path = REPO_ROOT) -> list[str]:
    """Repo-relative citation paths that do not resolve on disk."""
    missing = []
    for record in records:
        for citation in record.citations:
            if not (Path(root) / citation.path).is_file():
                missing.append(citation.path)
    return sorted(set(missing))


def candidate_gates(record: CandidateRecord, root: Path = REPO_ROOT) -> dict:
    """The checks that decide whether a candidate may be traded."""
    citations_present = bool(record.citations) and not [
        citation.path
        for citation in record.citations
        if not (Path(root) / citation.path).is_file()
    ]
    accepted = record.status == STATUS_ACCEPTED
    return {
        "accepted": accepted,
        "has_citations": bool(record.citations),
        "citations_present": citations_present,
        "tradable": bool(accepted and citations_present),
    }


def rank_candidates(records) -> list[CandidateRecord]:
    """Accepted candidates first, then research, then rejected."""
    return sorted(
        records,
        key=lambda record: (
            _STATUS_ORDER.get(record.status, 99),
            _KIND_ORDER.get(record.kind, 99),
            record.name,
        ),
    )


def ranking_table(records, root: Path = REPO_ROOT) -> list[dict]:
    """The evidence-ranked table, ready for the report writer."""
    rows = []
    for rank, record in enumerate(rank_candidates(records), start=1):
        rows.append(
            {
                "rank": rank,
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
                "gates": candidate_gates(record, root=root),
            }
        )
    return rows


def select_tradable(records, root: Path = REPO_ROOT) -> CandidateRecord | None:
    """The single candidate the bot may act on, or None to stand down."""
    tradable = [
        record
        for record in records
        if candidate_gates(record, root=root)["tradable"]
    ]
    if len(tradable) != 1:
        return None
    return tradable[0]
