"""End-to-end tests for Shopify ingestion (Phase 2 scope)."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.exceptions import SchemaError
from src.ingestion.shopify import ingest_shopify, read_shopify_csv

FIXTURES = Path(__file__).parent / "fixtures"


def test_read_clean_fixture() -> None:
    df = read_shopify_csv(FIXTURES / "shopify_clean.csv")
    assert len(df) == 5
    assert "Order ID" in df.columns
    assert "Created at" in df.columns


def test_read_missing_file_raises() -> None:
    with pytest.raises(SchemaError, match="not found"):
        read_shopify_csv(FIXTURES / "does_not_exist.csv")


def test_read_empty_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(SchemaError, match="empty"):
        read_shopify_csv(p)


def test_ingest_clean_fixture_all_accepted() -> None:
    result, report = ingest_shopify(FIXTURES / "shopify_clean.csv")
    assert len(result.accepted) == 5
    assert len(result.rejected) == 0
    assert report.rows_accepted == 5
    assert report.rows_rejected == 0
    # Canonical columns present
    assert "order_id" in result.accepted.columns
    assert "created_at" in result.accepted.columns
    assert "gross_amount" in result.accepted.columns
    # Raw header names gone
    assert "Order ID" not in result.accepted.columns
    assert "Created at" not in result.accepted.columns


def test_ingest_dirty_fixture_rejects_expected_rows() -> None:
    result, report = ingest_shopify(FIXTURES / "shopify_dirty.csv")

    # Fixture has 10 data rows (header + 10 rows of data), no blank lines.
    # Expected outcomes:
    #   Row 2 (2001):                       accepted (valid)
    #   Row 3 (2002 first occurrence):      accepted
    #   Row 4 (2002 second occurrence):     rejected -> duplicate_order_id
    #   Row 5 (empty order_id):             rejected -> missing_required_value
    #   Row 6 (2004, missing money cols):   rejected -> missing_required_value
    #   Row 7 (2005, missing created_at):   rejected -> missing_required_value
    #   Row 8 (2006, "not_a_number"):       accepted (Phase 2 is structural only)
    #   Row 9 (2007, "not-a-date"):         accepted (Phase 2 is structural only)
    #   Row 10 (2008, tz trap):             accepted
    #   Row 11 (2009, cancelled):           accepted
    # Totals: 6 accepted, 4 rejected.
    assert report.rows_received == 10
    assert report.rows_rejected == 4
    assert report.rows_accepted == 6

    reasons = report.rejection_reasons
    assert reasons.get("duplicate_order_id", 0) == 1
    assert reasons.get("missing_required_value", 0) == 3
    assert "empty_row" not in reasons  # no blank lines in this fixture


def test_ingest_dirty_fixture_accepted_rows_include_semantically_invalid() -> None:
    """Rows with bad dates/money/status are structurally fine and accepted here."""
    result, _ = ingest_shopify(FIXTURES / "shopify_dirty.csv")
    accepted_ids = set(result.accepted["order_id"])
    # These rows have non-parseable values but are structurally valid.
    assert "2006" in accepted_ids  # money: "not_a_number"
    assert "2007" in accepted_ids  # date: "not-a-date"
    assert "2009" in accepted_ids  # status: "cancelled"


def test_ingest_dirty_fixture_unexpected_column_warned(caplog) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    ingest_shopify(FIXTURES / "shopify_dirty.csv")
    assert any("Unexpected Shopify columns" in r.message for r in caplog.records)
