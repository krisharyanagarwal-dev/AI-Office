"""Tests for reconciling the local harness against the archived carry audit.

The registry cites the archived out-of-sample numbers (BTC 350.30, ETH 253.54).
Those numbers were produced by a different data window and a zero-entry-cost
convention, so a local re-run must reconcile against them explicitly rather
than leave two unexplained numbers side by side in the report.
"""
import json

import pytest

from best_signal.evidence import CARRY_OOS_AUDIT, REPO_ROOT
from best_signal.funding import DEFAULT_DATA_DIR, FundingPrint, load_symbol_prints
from best_signal.validate import reconcile_archive_audit, reconcile_archive_window

AUDIT_PATH = REPO_ROOT / CARRY_OOS_AUDIT

ARCHIVED_CONTROL = "always_short_perp_side_plus1"
PUBLISHED_OOS_NETS = {"BTCUSDT": 350.30, "ETHUSDT": 253.54}


def make_prints(rates, start_ms=0, step_ms=8 * 3600 * 1000):
    return [
        FundingPrint(ts_ms=start_ms + index * step_ms, rate=rate)
        for index, rate in enumerate(rates)
    ]


def load_audit():
    if not AUDIT_PATH.is_file():
        pytest.skip("archived carry audit is not present")
    return json.loads(AUDIT_PATH.read_text())


def test_reconciliation_reproduces_the_archived_carry_audit_numbers():
    audit = load_audit()
    for symbol, published in PUBLISHED_OOS_NETS.items():
        archived = audit["symbols"][symbol]
        control = archived["no_information_controls"]["out_of_sample"][ARCHIVED_CONTROL]
        assert control["net"] == pytest.approx(published)
        assert control["flips"] == 0
        assert control["fees"] == 0.0

        prints = load_symbol_prints(symbol, data_dir=DEFAULT_DATA_DIR)
        row = reconcile_archive_window(
            prints,
            archived["first_ts"],
            archived["last_ts"],
            archived_net=control["net"],
            archived_collected=control["collected"],
            archived_records=archived["records"],
        )

        assert row["status"] == "reproduced"
        assert row["local_records"] == archived["records"]
        assert row["oos_prints"] == archived["split_sizes"]["out_of_sample"]
        assert row["local_oos_collected"] == pytest.approx(control["collected"], abs=0.01)
        assert row["collected_matches_archive"] is True
        assert row["local_oos_net"] == pytest.approx(control["net"] - 10.0, abs=0.01)
        assert row["local_oos_fees"] == pytest.approx(10.0)


def test_reconciliation_explains_the_entry_cost_gap():
    prints = make_prints([0.0002] * 300)
    row = reconcile_archive_window(
        prints,
        prints[0].ts_ms,
        prints[-1].ts_ms,
        archived_net=150.0,
        archived_collected=150.0,
    )
    assert row["status"] == "reproduced"
    assert row["local_oos_collected"] == pytest.approx(150.0)
    assert row["local_oos_net"] == pytest.approx(140.0)
    assert row["local_oos_fees"] == pytest.approx(10.0)
    assert "entry" in row["explanation"].lower()


def test_reconciliation_reports_missing_local_data_instead_of_raising():
    prints = make_prints([0.0002] * 50)
    row = reconcile_archive_window(
        prints,
        prints[0].ts_ms + 10_000_000_000,
        prints[-1].ts_ms + 10_000_000_000,
        archived_net=10.0,
    )
    assert row["status"] == "no_local_data"
    assert row["local_records"] == 0
    assert row["collected_matches_archive"] is False


def test_archive_audit_reconciliation_reproduces_every_symbol_in_the_audit():
    audit = load_audit()
    prints_by_symbol = {
        symbol: load_symbol_prints(symbol, data_dir=DEFAULT_DATA_DIR)
        for symbol in audit["symbols"]
    }
    rows = reconcile_archive_audit(prints_by_symbol, audit_path=AUDIT_PATH)

    assert set(rows) == set(audit["symbols"])
    for symbol, row in rows.items():
        archived_net = audit["symbols"][symbol]["no_information_controls"][
            "out_of_sample"
        ][ARCHIVED_CONTROL]["net"]
        assert row["status"] == "reproduced"
        assert row["collected_matches_archive"] is True
        assert row["local_oos_net"] == pytest.approx(archived_net - 10.0, abs=0.01)


def test_archive_audit_reconciliation_reports_a_missing_audit_instead_of_raising(
    tmp_path,
):
    rows = reconcile_archive_audit(
        {"BTCUSDT": make_prints([0.0002] * 50)},
        audit_path=tmp_path / "missing_audit.json",
    )
    assert rows["BTCUSDT"]["status"] == "audit_unavailable"
    assert rows["BTCUSDT"]["collected_matches_archive"] is False


def test_archive_audit_reconciliation_flags_a_symbol_the_archive_never_audited():
    rows = reconcile_archive_audit(
        {"SOLUSDT": make_prints([0.0002] * 50)},
        audit_path=AUDIT_PATH,
    )
    assert rows["SOLUSDT"]["status"] == "not_in_archive"
    assert rows["SOLUSDT"]["collected_matches_archive"] is False
