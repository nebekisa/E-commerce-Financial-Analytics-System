"""Tests for src/reporting/export.py."""

from __future__ import annotations

import csv
import io
from datetime import date

import pandas as pd
from src.reporting.export import (
    EXPORT_COLUMNS,
    EXPORT_HEADERS,
    model_to_csv_bytes,
)


def _model(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "calendar_date" in df.columns:
        df["calendar_date"] = pd.to_datetime(df["calendar_date"])
    return df


def _full_row(**overrides: object) -> dict:
    defaults = {
        "calendar_date": date(2026, 9, 1),
        "gross_revenue": 1000.0,
        "discount_amount": 100.0,
        "net_revenue": 900.0,
        "taxes": 135.0,
        "shipping_fees": 50.0,
        "orders": 1,
        "ad_spend": 130.0,
        "impressions": 5000,
        "link_clicks": 100,
        "cogs_estimate": 400.0,
        "contribution_margin": 370.0,
        "roas": 6.923076923,
        "mer": 0.1444444444,
        "profit_margin": 0.4111111111,
        "reporting_currency": "ETB",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------- #
# Structure                                                               #
# ---------------------------------------------------------------------- #


def test_empty_model_produces_headers_only() -> None:
    df = _model([])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    # First row is the header.
    assert len(rows) == 1
    # Headers should be human-readable names, not model column names.
    assert "Date" in rows[0]
    assert "Net Revenue" in rows[0]
    assert "calendar_date" not in rows[0]


def test_full_row_produces_all_columns() -> None:
    df = _model([_full_row()])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    row = next(reader)
    assert row["Date"] == "2026-09-01"
    assert row["Net Revenue"] == "900.0"
    assert row["Currency"] == "ETB"


def test_date_formatted_as_iso() -> None:
    df = _model([_full_row(calendar_date=date(2026, 9, 15))])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    assert "2026-09-15" in text
    # Ensure the row doesn't contain a full timestamp.
    assert "2026-09-15 00:00:00" not in text


def test_ratios_rounded_to_four_decimals() -> None:
    df = _model([_full_row(roas=6.923076923)])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    assert "6.9231" in text
    # Full precision should not be present.
    assert "6.923076923" not in text


def test_money_rounded_to_two_decimals() -> None:
    df = _model([_full_row(net_revenue=900.123456)])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    assert "900.12" in text


def test_null_values_written_as_empty() -> None:
    """A NULL impression count must be an empty cell, not "nan"."""
    df = _model([_full_row(impressions=None, link_clicks=None)])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    assert "nan" not in text.lower()
    reader = csv.DictReader(io.StringIO(text))
    row = next(reader)
    assert row["Impressions"] == ""
    assert row["Link Clicks"] == ""


def test_column_order_matches_export_contract() -> None:
    """The header order in the CSV must match EXPORT_COLUMNS order."""
    df = _model([_full_row()])
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    expected = [EXPORT_HEADERS[c] for c in EXPORT_COLUMNS]
    assert header == expected


def test_missing_columns_are_omitted() -> None:
    """If the model lacks some export columns, the CSV omits them gracefully."""
    df = pd.DataFrame(
        {
            "calendar_date": pd.to_datetime([date(2026, 9, 1)]),
            "net_revenue": [100.0],
        }
    )
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    row = next(reader)
    assert "Date" in row
    assert "Net Revenue" in row
    assert "ROAS" not in row


def test_multiple_rows_preserve_order() -> None:
    df = _model(
        [
            _full_row(calendar_date=date(2026, 9, 1), net_revenue=100.0),
            _full_row(calendar_date=date(2026, 9, 2), net_revenue=200.0),
            _full_row(calendar_date=date(2026, 9, 3), net_revenue=300.0),
        ]
    )
    csv_bytes = model_to_csv_bytes(df)
    text = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert [r["Date"] for r in rows] == ["2026-09-01", "2026-09-02", "2026-09-03"]
