"""Tests for the SQL financial model.

These tests load synthetic cleaned DataFrames into DuckDB, run sql/*.sql,
and assert on the resulting daily_financial_model.

Every test has a hand-computable expected value, documented in the
docstring, so the arithmetic can be verified without reading the SQL.

Type notes:
    - DuckDB's DATE columns come back as pandas Timestamps through fetchdf().
      Use `_as_dates()` or `.date()` for comparison against date literals.
    - Empty DataFrames loaded into DuckDB must have explicit dtypes, or
      DuckDB infers INTEGER from empty object columns, which breaks
      downstream COALESCE. Use `_empty_shopify_df()` and `_empty_meta_df()`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from src.database.duckdb_engine import (
    close_database,
    execute_sql_directory,
    load_dataframe,
    open_database,
    read_table,
)

SQL_DIR = Path(__file__).parent.parent / "sql"


# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #


@pytest.fixture
def conn(tmp_path: Path):
    c = open_database(tmp_path / "model.duckdb")
    c.execute("SET VARIABLE cogs_percentage = 0.4;")
    yield c
    close_database(c)


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _as_dates(series: pd.Series) -> list:
    """Convert a Timestamp series to Python date objects for comparison."""
    return [ts.date() if pd.notna(ts) else None for ts in series]


def _empty_shopify_df() -> pd.DataFrame:
    """An empty Shopify clean DataFrame with explicit dtypes."""
    return pd.DataFrame(
        {
            "order_id": pd.Series([], dtype="string"),
            "calendar_date": pd.Series([], dtype="datetime64[ns]"),
            "created_at_utc": pd.Series([], dtype="datetime64[ns, UTC]"),
            "financial_status": pd.Series([], dtype="string"),
            "gross_amount": pd.Series([], dtype="float64"),
            "discount_amount": pd.Series([], dtype="float64"),
            "net_amount": pd.Series([], dtype="float64"),
            "taxes": pd.Series([], dtype="float64"),
            "shipping_fees": pd.Series([], dtype="float64"),
            "reporting_currency": pd.Series([], dtype="string"),
        }
    )


def _empty_meta_df() -> pd.DataFrame:
    """An empty Meta clean DataFrame with explicit dtypes."""
    return pd.DataFrame(
        {
            "calendar_date": pd.Series([], dtype="datetime64[ns]"),
            "campaign_name": pd.Series([], dtype="string"),
            "spend_amount": pd.Series([], dtype="float64"),
            "impressions": pd.Series([], dtype="Int64"),
            "link_clicks": pd.Series([], dtype="Int64"),
            "reporting_currency": pd.Series([], dtype="string"),
        }
    )


def _load_and_run(conn, shopify_df: pd.DataFrame, meta_df: pd.DataFrame) -> pd.DataFrame:
    load_dataframe(conn, shopify_df, "shopify_orders_clean")
    load_dataframe(conn, meta_df, "meta_ads_clean")
    execute_sql_directory(conn, SQL_DIR)
    return read_table(conn, "daily_financial_model")


def _shopify_row(
    order_id: str,
    calendar_date: date,
    net: float,
    gross: float | None = None,
    discount: float = 0.0,
    taxes: float = 0.0,
    shipping: float = 0.0,
) -> dict:
    return {
        "order_id": order_id,
        "calendar_date": pd.Timestamp(calendar_date),
        "created_at_utc": pd.Timestamp(calendar_date, tz="UTC"),
        "financial_status": "paid",
        "gross_amount": gross if gross is not None else net,
        "discount_amount": discount,
        "net_amount": net,
        "taxes": taxes,
        "shipping_fees": shipping,
        "reporting_currency": "ETB",
    }


def _meta_row(
    calendar_date: date,
    spend: float,
    campaign: str = "A",
    impressions: int | None = 1000,
    clicks: int | None = 50,
) -> dict:
    return {
        "calendar_date": pd.Timestamp(calendar_date),
        "campaign_name": campaign,
        "spend_amount": spend,
        "impressions": impressions,
        "link_clicks": clicks,
        "reporting_currency": "ETB",
    }


# ---------------------------------------------------------------------- #
# Single-day scenarios                                                    #
# ---------------------------------------------------------------------- #


def test_single_day_both_sources(conn) -> None:
    """Hand calculation:
    gross = 1000, discount = 100, net = 900
    ad_spend = 130
    cogs = 0.4 * 1000 = 400
    contribution_margin = 900 - 130 - 400 = 370
    roas = 900 / 130 ≈ 6.923
    mer = 130 / 900 ≈ 0.1444
    profit_margin = 370 / 900 ≈ 0.4111
    """
    shopify = pd.DataFrame([_shopify_row("1", date(2026, 9, 1), net=900, gross=1000, discount=100)])
    meta = pd.DataFrame([_meta_row(date(2026, 9, 1), spend=130)])
    result = _load_and_run(conn, shopify, meta)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["calendar_date"].date() == date(2026, 9, 1)
    assert row["gross_revenue"] == 1000.0
    assert row["net_revenue"] == 900.0
    assert row["ad_spend"] == 130.0
    assert row["orders"] == 1
    assert row["cogs_estimate"] == pytest.approx(400.0)
    assert row["contribution_margin"] == pytest.approx(370.0)
    assert row["roas"] == pytest.approx(900 / 130)
    assert row["mer"] == pytest.approx(130 / 900)
    assert row["profit_margin"] == pytest.approx(370 / 900)


def test_single_day_shopify_only(conn) -> None:
    """Revenue but no spend.
    net_revenue = 100, ad_spend = 0
    roas = 100 / 0 → NULL  (guarded by WHEN ad_spend > 0)
    mer = 0 / 100 = 0.0    (division valid, no spend)
    """
    shopify = pd.DataFrame([_shopify_row("1", date(2026, 9, 1), net=100)])
    meta = _empty_meta_df()
    result = _load_and_run(conn, shopify, meta)

    row = result.iloc[0]
    assert row["net_revenue"] == 100.0
    assert row["ad_spend"] == 0.0
    assert pd.isna(row["roas"])
    assert row["mer"] == 0.0


def test_single_day_meta_only(conn) -> None:
    """Spend but no revenue.
    net_revenue = 0, ad_spend = 100
    roas = 0 / 100 = 0.0     (division valid, no revenue)
    mer = 100 / 0 → NULL     (guarded by WHEN net_revenue > 0)
    profit_margin = -100 / 0 → NULL
    contribution_margin = 0 - 100 - 0 = -100
    """
    shopify = _empty_shopify_df()
    meta = pd.DataFrame([_meta_row(date(2026, 9, 1), spend=100)])
    result = _load_and_run(conn, shopify, meta)

    row = result.iloc[0]
    assert row["net_revenue"] == 0.0
    assert row["ad_spend"] == 100.0
    assert row["contribution_margin"] == pytest.approx(-100.0)
    assert row["roas"] == 0.0
    assert pd.isna(row["mer"])
    assert pd.isna(row["profit_margin"])


# ---------------------------------------------------------------------- #
# Multi-day and gaps                                                      #
# ---------------------------------------------------------------------- #


def test_date_spine_fills_gaps(conn) -> None:
    """Shopify on Sep 1 and Sep 3, Meta on Sep 3. Sep 2 should appear with 0s."""
    shopify = pd.DataFrame(
        [
            _shopify_row("1", date(2026, 9, 1), net=100),
            _shopify_row("2", date(2026, 9, 3), net=200),
        ]
    )
    meta = pd.DataFrame([_meta_row(date(2026, 9, 3), spend=50)])
    result = _load_and_run(conn, shopify, meta)

    assert len(result) == 3
    assert _as_dates(result["calendar_date"]) == [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
    ]

    sep2 = result[result["calendar_date"].dt.date == date(2026, 9, 2)].iloc[0]
    assert sep2["net_revenue"] == 0.0
    assert sep2["ad_spend"] == 0.0
    assert sep2["orders"] == 0
    assert pd.isna(sep2["roas"])


def test_null_impressions_preserved(conn) -> None:
    """A day with Meta spend but no impression data should have NULL impressions."""
    shopify = pd.DataFrame([_shopify_row("1", date(2026, 9, 1), net=100)])
    meta = pd.DataFrame([_meta_row(date(2026, 9, 1), spend=50, impressions=None, clicks=None)])
    result = _load_and_run(conn, shopify, meta)
    row = result.iloc[0]
    assert pd.isna(row["impressions"])
    assert pd.isna(row["link_clicks"])


# ---------------------------------------------------------------------- #
# COGS percentage override                                                #
# ---------------------------------------------------------------------- #


def test_cogs_percentage_is_configurable(conn) -> None:
    """Changing the session variable changes COGS and contribution margin."""
    conn.execute("SET VARIABLE cogs_percentage = 0.25;")
    shopify = pd.DataFrame([_shopify_row("1", date(2026, 9, 1), net=900, gross=1000)])
    meta = pd.DataFrame([_meta_row(date(2026, 9, 1), spend=100)])
    result = _load_and_run(conn, shopify, meta)
    row = result.iloc[0]
    assert row["cogs_estimate"] == pytest.approx(250.0)
    assert row["contribution_margin"] == pytest.approx(900 - 100 - 250)


# ---------------------------------------------------------------------- #
# Empty inputs                                                            #
# ---------------------------------------------------------------------- #


def test_both_empty_produces_empty_model(conn) -> None:
    result = _load_and_run(conn, _empty_shopify_df(), _empty_meta_df())
    assert len(result) == 0
