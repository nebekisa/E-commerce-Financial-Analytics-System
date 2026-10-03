"""End-to-end test against a hand-calculated golden dataset.

This is the single most important test in the suite. It proves that the
entire pipeline — ingestion, header mapping, validation, transformation,
date/time handling, currency conversion, SQL modeling — produces the exact
numbers a human would compute by hand.

If this test fails, the business numbers are wrong, regardless of how many
unit tests pass.

The golden dataset is defined in tests/fixtures/golden_shopify.csv and
tests/fixtures/golden_meta.csv. The expected values are documented in the
module docstring of this file and reproduced inline in each assertion.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from config.settings import Settings
from src.database.duckdb_engine import (
    close_database,
    execute_sql_directory,
    load_dataframe,
    open_database,
    read_table,
)
from src.ingestion.meta_ads import ingest_meta_ads
from src.ingestion.shopify import ingest_shopify
from src.transformation.meta_transform import transform_meta_ads
from src.transformation.shopify_transform import transform_shopify

FIXTURES = Path(__file__).parent / "fixtures"
SQL_DIR = Path(__file__).parent.parent / "sql"


# ---------------------------------------------------------------------- #
# Expected values — hand-calculated from the golden dataset               #
#                                                                         #
# FX: 1 USD = 130 ETB. COGS: 40% of gross.                                #
#                                                                         #
# | Date   | gross | disc | net  | ord | ad_spend | cogs | contrib | roas     | mer      | margin    |
# |--------|-------|------|------|-----|----------|------|---------|----------|----------|-----------|
# | 09-01  |  1500 |  100 | 1400 |   2 |     9100 |  600 |   -8300 | 0.153846 | 6.5      | -5.928571 |
# | 09-02  |  1000 |   50 |  950 |   2 |     5200 |  400 |   -4650 | 0.182692 | 5.473684 | -4.894736 |
# | 09-03  |   600 |    0 |  600 |   1 |     3900 |  240 |   -3540 | 0.153846 | 6.5      | -5.9      |
# | 09-04  |   700 |   70 |  630 |   1 |        0 |  280 |     350 | NULL     | 0.0      |  0.555556 |
# | 09-05  |     0 |    0 |    0 |   0 |     1300 |    0 |   -1300 | 0.0      | NULL     | NULL      |
#
# Notes on the dataset's edge cases:
#   * S003 (Sep 1 22:30 UTC) belongs to Sep 2 in Addis time. If this test
#     ever puts S003's revenue on Sep 1, the timezone conversion is broken.
#   * S005 (cancelled) and S007 (refunded) must not contribute to revenue.
#   * Sep 4 has Shopify-only data. Meta columns must be NULL, not 0.
#   * Sep 5 has Meta-only data. Shopify columns must be 0, not NULL.
# ---------------------------------------------------------------------- #


EXPECTED = {
    date(2026, 9, 1): {
        "gross_revenue": 1500.0,
        "discount_amount": 100.0,
        "net_revenue": 1400.0,
        "orders": 2,
        "ad_spend": 9100.0,
        "impressions": 14000,
        "link_clicks": 280,
        "cogs_estimate": 600.0,
        "contribution_margin": -8300.0,
        "roas": 1400 / 9100,
        "mer": 9100 / 1400,
        "profit_margin": -8300 / 1400,
    },
    date(2026, 9, 2): {
        "gross_revenue": 1000.0,
        "discount_amount": 50.0,
        "net_revenue": 950.0,
        "orders": 2,
        "ad_spend": 5200.0,
        "impressions": 8000,
        "link_clicks": 160,
        "cogs_estimate": 400.0,
        "contribution_margin": -4650.0,
        "roas": 950 / 5200,
        "mer": 5200 / 950,
        "profit_margin": -4650 / 950,
    },
    date(2026, 9, 3): {
        "gross_revenue": 600.0,
        "discount_amount": 0.0,
        "net_revenue": 600.0,
        "orders": 1,
        "ad_spend": 3900.0,
        "impressions": 6000,
        "link_clicks": 120,
        "cogs_estimate": 240.0,
        "contribution_margin": -3540.0,
        "roas": 600 / 3900,
        "mer": 3900 / 600,
        "profit_margin": -3540 / 600,
    },
    date(2026, 9, 4): {
        "gross_revenue": 700.0,
        "discount_amount": 70.0,
        "net_revenue": 630.0,
        "orders": 1,
        "ad_spend": 0.0,
        "impressions": None,  # NULL, not 0
        "link_clicks": None,  # NULL, not 0
        "cogs_estimate": 280.0,
        "contribution_margin": 350.0,
        "roas": None,  # ad_spend = 0 → NULL
        "mer": 0.0,  # 0 / 630 = 0
        "profit_margin": 350 / 630,
    },
    date(2026, 9, 5): {
        "gross_revenue": 0.0,
        "discount_amount": 0.0,
        "net_revenue": 0.0,
        "orders": 0,
        "ad_spend": 1300.0,
        "impressions": 2000,
        "link_clicks": 40,
        "cogs_estimate": 0.0,
        "contribution_margin": -1300.0,
        "roas": 0.0,  # 0 / 1300 = 0
        "mer": None,  # net_revenue = 0 → NULL
        "profit_margin": None,  # net_revenue = 0 → NULL
    },
}


# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #


@pytest.fixture
def golden_settings() -> Settings:
    return Settings(
        reporting_currency="ETB",
        reporting_timezone="Africa/Addis_Ababa",
        shopify_source_currency="ETB",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("130.0"),
        etb_to_reporting_fx_rate=Decimal("1.0"),
        cogs_percentage=Decimal("0.40"),
    )


@pytest.fixture
def golden_model(tmp_path: Path, golden_settings: Settings) -> pd.DataFrame:
    """Run the full pipeline on the golden dataset and return the model."""
    # --- Ingest ---
    shopify_result, _ = ingest_shopify(FIXTURES / "golden_shopify.csv")
    meta_result, _ = ingest_meta_ads(FIXTURES / "golden_meta.csv")

    # --- Transform ---
    from src.validation.validators import DQReport

    shopify_clean, _ = transform_shopify(
        shopify_result.accepted,
        settings=golden_settings,
        report=DQReport(source="shopify"),
    )
    meta_clean, _ = transform_meta_ads(
        meta_result.accepted,
        settings=golden_settings,
        report=DQReport(source="meta_ads"),
    )

    # --- Load into DuckDB and run the model ---
    conn = open_database(tmp_path / "golden.duckdb")
    try:
        load_dataframe(conn, shopify_clean, "shopify_orders_clean")
        load_dataframe(conn, meta_clean, "meta_ads_clean")
        conn.execute(f"SET VARIABLE cogs_percentage = {float(golden_settings.cogs_percentage)};")
        execute_sql_directory(conn, SQL_DIR)
        return read_table(conn, "daily_financial_model")
    finally:
        close_database(conn)


# ---------------------------------------------------------------------- #
# Tests                                                                   #
# ---------------------------------------------------------------------- #


def test_model_has_exactly_five_dates(golden_model: pd.DataFrame) -> None:
    """The date spine should cover Sep 1 through Sep 5, no more, no less."""
    dates = [ts.date() for ts in golden_model["calendar_date"]]
    assert dates == [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 5),
    ]


@pytest.mark.parametrize("target_date", sorted(EXPECTED.keys()))
def test_daily_values_match_hand_calculation(golden_model: pd.DataFrame, target_date: date) -> None:
    """Every column on every date must match the hand-calculated expectation."""
    row = golden_model[golden_model["calendar_date"].dt.date == target_date]
    assert len(row) == 1, f"Expected exactly one row for {target_date}"
    row = row.iloc[0]
    expected = EXPECTED[target_date]

    for column, expected_value in expected.items():
        actual_value = row[column]
        if expected_value is None:
            assert pd.isna(
                actual_value
            ), f"{target_date} {column}: expected NULL, got {actual_value!r}"
        elif isinstance(expected_value, float):
            assert actual_value == pytest.approx(expected_value), (
                f"{target_date} {column}: expected {expected_value}, " f"got {actual_value}"
            )
        else:
            assert actual_value == expected_value, (
                f"{target_date} {column}: expected {expected_value}, " f"got {actual_value}"
            )


def test_timezone_trap_order_on_correct_date(golden_model: pd.DataFrame) -> None:
    """S003 (Sep 1 22:30 UTC) must be attributed to Sep 2 in Addis time.

    Sep 1 has 2 orders (S001, S002), Sep 2 has 2 orders (S003, S004).
    If timezone conversion is broken, Sep 1 would have 3 orders and Sep 2
    would have 1.
    """
    sep1 = golden_model[golden_model["calendar_date"].dt.date == date(2026, 9, 1)].iloc[0]
    sep2 = golden_model[golden_model["calendar_date"].dt.date == date(2026, 9, 2)].iloc[0]
    assert sep1["orders"] == 2
    assert sep2["orders"] == 2
    # Sep 1 net_revenue = 900 + 500 = 1400 (not 1600, which would include S003).
    assert sep1["net_revenue"] == pytest.approx(1400.0)
    # Sep 2 net_revenue = 200 + 750 = 950 (not 750, which would exclude S003).
    assert sep2["net_revenue"] == pytest.approx(950.0)


def test_excluded_statuses_not_in_revenue(golden_model: pd.DataFrame) -> None:
    """S005 (cancelled) and S007 (refunded) must not contribute to any date."""
    # Total net_revenue across all dates = 1400 + 950 + 600 + 630 + 0 = 3580.
    # If cancelled or refunded orders leaked in, this would be higher.
    total_net = golden_model["net_revenue"].sum()
    assert total_net == pytest.approx(3580.0)


def test_meta_only_date_has_null_shopify_free_meta_columns(golden_model: pd.DataFrame) -> None:
    """Sep 5 has Meta spend but no Shopify orders.
    ad_spend is 1300, Shopify monetary columns are 0.
    """
    sep5 = golden_model[golden_model["calendar_date"].dt.date == date(2026, 9, 5)].iloc[0]
    assert sep5["ad_spend"] == pytest.approx(1300.0)
    assert sep5["net_revenue"] == 0.0
    assert sep5["orders"] == 0


def test_shopify_only_date_has_null_impressions(golden_model: pd.DataFrame) -> None:
    """Sep 4 has Shopify revenue but no Meta rows.
    impressions and link_clicks must be NULL, not 0.
    """
    sep4 = golden_model[golden_model["calendar_date"].dt.date == date(2026, 9, 4)].iloc[0]
    assert sep4["net_revenue"] == pytest.approx(630.0)
    assert sep4["ad_spend"] == 0.0
    assert pd.isna(sep4["impressions"])
    assert pd.isna(sep4["link_clicks"])


def test_currency_conversion_applied(golden_model: pd.DataFrame) -> None:
    """Meta spend in USD, converted to ETB at 130.0.
    Sep 1 raw: 50 + 20 = 70 USD. Converted: 70 * 130 = 9100 ETB.
    """
    sep1 = golden_model[golden_model["calendar_date"].dt.date == date(2026, 9, 1)].iloc[0]
    assert sep1["ad_spend"] == pytest.approx(9100.0)


def test_totals_across_dataset(golden_model: pd.DataFrame) -> None:
    """Aggregate totals across all 5 days, hand-calculated."""
    assert golden_model["net_revenue"].sum() == pytest.approx(3580.0)
    assert golden_model["ad_spend"].sum() == pytest.approx(19500.0)
    assert golden_model["contribution_margin"].sum() == pytest.approx(-17440.0)
    assert golden_model["orders"].sum() == 6  # S001, S002, S003, S004, S006, S008
    # Total impressions = 14000 + 8000 + 6000 + NULL + 2000 = 30000
    # (NULL is ignored by sum, which matches SQL semantics.)
    assert golden_model["impressions"].sum() == 30000
