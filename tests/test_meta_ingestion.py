"""End-to-end tests for Meta Ads ingestion (Phase 3 scope)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from src.exceptions import SchemaError
from src.ingestion.meta_ads import ingest_meta_ads, read_meta_csv

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------- #
# read_meta_csv                                                           #
# ---------------------------------------------------------------------- #


def test_read_clean_fixture() -> None:
    df = read_meta_csv(FIXTURES / "meta_clean.csv")
    assert len(df) == 5
    assert "Reporting Start" in df.columns
    assert "Amount Spent (USD)" in df.columns


def test_read_missing_file_raises() -> None:
    with pytest.raises(SchemaError, match="not found"):
        read_meta_csv(FIXTURES / "does_not_exist.csv")


def test_read_empty_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(SchemaError, match="empty"):
        read_meta_csv(p)


# ---------------------------------------------------------------------- #
# ingest_meta_ads                                                         #
# ---------------------------------------------------------------------- #


def test_ingest_clean_fixture_all_accepted() -> None:
    result, report = ingest_meta_ads(FIXTURES / "meta_clean.csv")
    assert len(result.accepted) == 5
    assert len(result.rejected) == 0
    assert report.rows_accepted == 5
    assert report.rows_rejected == 0
    # Canonical columns present
    assert "reporting_start" in result.accepted.columns
    assert "reporting_end" in result.accepted.columns
    assert "spend_amount" in result.accepted.columns
    assert "campaign_name" in result.accepted.columns
    assert "impressions" in result.accepted.columns
    assert "link_clicks" in result.accepted.columns
    # Raw header names gone
    assert "Reporting Start" not in result.accepted.columns
    assert "Amount Spent (USD)" not in result.accepted.columns


def test_ingest_dirty_fixture_rejects_expected_rows() -> None:
    result, report = ingest_meta_ads(FIXTURES / "meta_dirty.csv")

    # Fixture has 9 data rows.
    # Rejections (all missing_required_value):
    #   Row 6 (2026-09-05): missing spend_amount
    #   Row 7 (2026-09-06): missing reporting_end
    #   Row 8 (empty start): missing reporting_start
    # Accepted (6): rows 1, 2, 3, 4, 5, 9.
    assert report.rows_received == 9
    assert report.rows_rejected == 3
    assert report.rows_accepted == 6

    reasons = report.rejection_reasons
    assert reasons.get("missing_required_value", 0) == 3


def test_ingest_dirty_fixture_accepts_multi_day_interval() -> None:
    """Multi-day intervals are structurally valid at Phase 3.

    Whether they are semantically valid is decided in Phase 4 (interval
    allocation strategy). Phase 3 must not reject them.
    """
    result, _ = ingest_meta_ads(FIXTURES / "meta_dirty.csv")
    multi_day = result.accepted[
        (result.accepted["reporting_start"] == "2026-09-01")
        & (result.accepted["reporting_end"] == "2026-09-07")
    ]
    assert len(multi_day) == 1


def test_ingest_dirty_fixture_accepts_null_campaign_name() -> None:
    """A row with a null campaign_name is valid; the null is carried forward."""
    result, _ = ingest_meta_ads(FIXTURES / "meta_dirty.csv")
    null_campaign = result.accepted[result.accepted["campaign_name"].isna()]
    assert len(null_campaign) == 1
    assert null_campaign.iloc[0]["reporting_start"] == "2026-09-02"


def test_ingest_dirty_fixture_accepts_null_tracking() -> None:
    """A row with null impressions/link_clicks is valid."""
    result, _ = ingest_meta_ads(FIXTURES / "meta_dirty.csv")
    null_tracking = result.accepted[
        result.accepted["impressions"].isna() & result.accepted["link_clicks"].isna()
    ]
    assert len(null_tracking) == 1
    assert null_tracking.iloc[0]["reporting_start"] == "2026-09-03"


def test_ingest_dirty_fixture_accepts_zero_spend() -> None:
    """Zero spend is valid data, not missing data."""
    result, _ = ingest_meta_ads(FIXTURES / "meta_dirty.csv")
    zero_spend = result.accepted[result.accepted["spend_amount"] == "0.00"]
    assert len(zero_spend) == 1


def test_ingest_dirty_fixture_no_unexpected_columns_warning(caplog) -> None:
    """The dirty fixture has no extra columns; verify no spurious warning."""
    caplog.set_level(logging.WARNING)
    ingest_meta_ads(FIXTURES / "meta_dirty.csv")
    unexpected_warnings = [r for r in caplog.records if "Unexpected Meta Ads columns" in r.message]
    assert unexpected_warnings == []
