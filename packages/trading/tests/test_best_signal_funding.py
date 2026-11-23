"""
Tests for the best-signal funding data layer.

The funding layer is the foundation of the best-signal bot: every claim the
bot makes about carry is derived from these prints, so the loader must not
reorder, drop, or reinterpret them.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from best_signal.funding import (
    PERIODS_PER_YEAR,
    FundingPrint,
    annualized_funding,
    load_funding_prints,
    load_symbol_prints,
    positive_print_fraction,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_PARQUET = REPO_ROOT / "packages/_archive/all-files/parquet"


class TestFundingPrint:
    def test_holds_timestamp_and_rate(self):
        print = FundingPrint(ts_ms=1_568_102_400_000, rate=0.0001)
        assert print.ts_ms == 1_568_102_400_000
        assert print.rate == 0.0001


class TestLoadFundingPrints:
    def test_parquet_load_sorts_chronologically(self, tmp_path):
        path = tmp_path / "BTCUSDT_funding.parquet"
        pd.DataFrame(
            {
                "fundingTime": [3_000_000, 1_000_000, 2_000_000],
                "fundingRate": [0.0003, 0.0001, 0.0002],
            }
        ).to_parquet(path)

        prints = load_funding_prints(path)

        assert [p.ts_ms for p in prints] == [1_000_000, 2_000_000, 3_000_000]
        assert [p.rate for p in prints] == pytest.approx([0.0001, 0.0002, 0.0003])

    def test_json_deep_file_load(self, tmp_path):
        path = tmp_path / "BTCUSDT_funding_deep.json"
        path.write_text(
            json.dumps(
                {
                    "funding": [
                        {"t": 2_000_000, "rate": 0.0002},
                        {"t": 1_000_000, "rate": 0.0001},
                    ]
                }
            )
        )

        prints = load_funding_prints(path)

        assert [p.ts_ms for p in prints] == [1_000_000, 2_000_000]
        assert [p.rate for p in prints] == pytest.approx([0.0001, 0.0002])

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_funding_prints(tmp_path / "nope.parquet")

    def test_unsupported_extension_raises(self, tmp_path):
        path = tmp_path / "funding.csv"
        path.write_text("ts,rate\n")
        with pytest.raises(ValueError):
            load_funding_prints(path)


class TestFundingStatistics:
    def test_annualized_funding_scales_mean_by_native_cadence(self):
        prints = [FundingPrint(ts_ms=i * 1, rate=0.0001) for i in range(3)]
        assert annualized_funding(prints) == pytest.approx(
            0.0001 * PERIODS_PER_YEAR
        )

    def test_annualized_funding_of_empty_history_is_zero(self):
        assert annualized_funding([]) == 0.0

    def test_positive_print_fraction(self):
        prints = [
            FundingPrint(ts_ms=1, rate=0.001),
            FundingPrint(ts_ms=2, rate=-0.001),
            FundingPrint(ts_ms=3, rate=0.001),
            FundingPrint(ts_ms=4, rate=0.001),
        ]
        assert positive_print_fraction(prints) == pytest.approx(0.75)


class TestArchiveFundingHistory:
    """The archived primary prints are the evidence base for the carry claim."""

    def test_btc_history_is_long_and_carry_positive(self):
        prints = load_symbol_prints("BTCUSDT")
        assert len(prints) > 7000
        assert annualized_funding(prints) > 0.05
        assert positive_print_fraction(prints) > 0.80

    def test_eth_history_is_long_and_carry_positive(self):
        prints = load_symbol_prints("ETHUSDT")
        assert len(prints) > 7000
        assert annualized_funding(prints) > 0.05
        assert positive_print_fraction(prints) > 0.80

    def test_archive_files_are_present_where_expected(self):
        assert (ARCHIVE_PARQUET / "BTCUSDT_funding.parquet").is_file()
        assert (ARCHIVE_PARQUET / "ETHUSDT_funding.parquet").is_file()
