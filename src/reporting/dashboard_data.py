"""Query helpers for the Streamlit dashboard.

The dashboard never queries DuckDB directly. It calls these functions, which
encapsulate:
    - connection management
    - date filtering
    - the exact columns the dashboard needs

Why a separate module?
    - Testable without Streamlit
    - Reusable by the CLI's future --export-csv flag (Phase 8b)
    - The dashboard's data contract lives in one place

Design:
    All functions return pandas DataFrames ready for st.dataframe / st.line_chart
    / st.download_button. No Streamlit imports. No formatting. No KPI math.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from config.settings import Settings
from src.database.duckdb_engine import (
    close_database,
    open_database,
    read_table,
)
from src.utils.logging_config import get_logger

log = get_logger(__name__)


# The columns the dashboard displays. Excludes internal debug columns.
DASHBOARD_COLUMNS: tuple[str, ...] = (
    "calendar_date",
    "gross_revenue",
    "discount_amount",
    "net_revenue",
    "taxes",
    "shipping_fees",
    "orders",
    "ad_spend",
    "impressions",
    "link_clicks",
    "cogs_estimate",
    "contribution_margin",
    "roas",
    "mer",
    "profit_margin",
    "reporting_currency",
)


def load_model(
    *,
    settings: Settings,
    date_from: date | None = None,
    date_to: date | None = None,
) -> pd.DataFrame:
    """Load the daily_financial_model, optionally filtered by date.

    Args:
        settings: Used for the database path.
        date_from: Inclusive lower bound. None = no lower bound.
        date_to: Inclusive upper bound. None = no upper bound.

    Returns:
        DataFrame with columns in DASHBOARD_COLUMNS, sorted by calendar_date.
        Empty DataFrame if no rows match.
    """
    conn = open_database(settings.database_path)
    try:
        df = read_table(conn, "daily_financial_model")
    finally:
        close_database(conn)

    if df.empty:
        return df

    # calendar_date comes back as datetime64 from DuckDB; keep it as Timestamp
    # for filtering, but downstream consumers can .dt.date if they need dates.
    if date_from is not None:
        df = df[df["calendar_date"].dt.date >= date_from]
    if date_to is not None:
        df = df[df["calendar_date"].dt.date <= date_to]

    # Reorder to the documented dashboard contract.
    present = [c for c in DASHBOARD_COLUMNS if c in df.columns]
    df = df[present].reset_index(drop=True)

    log.debug(
        "Loaded dashboard model: %d rows",
        len(df),
        extra={
            "context": {
                "rows": len(df),
                "date_from": str(date_from) if date_from else None,
                "date_to": str(date_to) if date_to else None,
            }
        },
    )

    return df


def get_date_range(settings: Settings) -> tuple[date, date] | None:
    """Return (min_date, max_date) from the model, or None if the model is empty.

    Returns None if:
        - the database file doesn't exist
        - the daily_financial_model table doesn't exist
        - the table exists but has no rows (min/max are NULL)

    Used to initialize the dashboard's date filter widget so the default
    range covers the full data.
    """
    if not settings.database_path.exists():
        return None

    conn = open_database(settings.database_path)
    try:
        # Guard: check the model table exists before querying it.
        # Information_schema is a DuckDB system catalog.
        exists_row = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'daily_financial_model'"
        ).fetchone()
        if not exists_row or exists_row[0] == 0:
            return None

        result = conn.execute(
            "SELECT MIN(calendar_date), MAX(calendar_date) " "FROM daily_financial_model"
        ).fetchone()
    finally:
        close_database(conn)

    if result is None or result[0] is None or result[1] is None:
        return None
    return result[0], result[1]


def model_exists(settings: Settings) -> bool:
    """True if the DuckDB file exists AND has a daily_financial_model table."""
    if not settings.database_path.exists():
        return False
    try:
        conn = open_database(settings.database_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'daily_financial_model'"
            ).fetchone()
            return bool(row and row[0] > 0)
        finally:
            close_database(conn)
    except Exception:
        # Any error reading the DB means "not usable for the dashboard".
        return False
