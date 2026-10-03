"""CSV export of the daily financial model.

Produces a clean, business-facing CSV. Column names are human-readable and
the order is fixed (defined by EXPORT_COLUMNS) so downstream consumers see a
consistent schema regardless of the DuckDB table's internal column order.

Design decisions:
    - Dates are formatted as YYYY-MM-DD strings, not Timestamps, so the CSV
      opens cleanly in Excel without locale-dependent interpretation.
    - NULL values are written as empty cells, not "nan" or "NULL". This is
      the convention most spreadsheet tools expect.
    - Monetary columns are rounded to 2 decimals. Ratios are rounded to 4.
      The rounding happens only in the export; the model keeps full precision.
    - The reporting currency is included as a column, not baked into headers.
      This keeps the schema stable if the currency changes.
"""

from __future__ import annotations

import io

import pandas as pd

# Business-facing column order. Human-readable header names are applied via
# a rename map at export time; the DataFrame itself uses the model's column
# names until export.
EXPORT_COLUMNS: tuple[str, ...] = (
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

# Human-readable header names for the CSV.
EXPORT_HEADERS: dict[str, str] = {
    "calendar_date": "Date",
    "gross_revenue": "Gross Revenue",
    "discount_amount": "Discounts",
    "net_revenue": "Net Revenue",
    "taxes": "Taxes",
    "shipping_fees": "Shipping Fees",
    "orders": "Orders",
    "ad_spend": "Ad Spend",
    "impressions": "Impressions",
    "link_clicks": "Link Clicks",
    "cogs_estimate": "COGS Estimate",
    "contribution_margin": "Contribution Margin",
    "roas": "ROAS",
    "mer": "Meta Spend / Net Revenue",
    "profit_margin": "Profit Margin",
    "reporting_currency": "Currency",
}

# Decimal places for each numeric column type. Default is 2.
_RATIO_COLUMNS = {"roas", "mer", "profit_margin"}
_RATIO_DECIMALS = 4
_MONEY_DECIMALS = 2


def model_to_csv_bytes(model: pd.DataFrame) -> bytes:
    """Serialize the model to CSV bytes suitable for st.download_button.

    Returns a UTF-8 encoded CSV with headers replaced by human-readable names
    and dates formatted as YYYY-MM-DD.

    Edge case: if the model has no columns at all, the CSV contains the full
    export schema (headers only). This lets a downstream consumer always
    read the column names, even when no data is present.
    """
    # Determine which export columns are available. If the model has no
    # columns at all, fall back to the full export schema so the header row
    # still communicates the contract.
    present = [c for c in EXPORT_COLUMNS if c in model.columns]
    if not present:
        present = list(EXPORT_COLUMNS)

    if model.empty:
        # Headers only, no rows. Include every column in `present` so the
        # schema is visible.
        empty = pd.DataFrame({c: [] for c in present})
        return _serialize(empty)

    # Select only export columns that exist in the input.
    df = model[present].copy()

    # Format dates as strings.
    if "calendar_date" in df.columns:
        df["calendar_date"] = pd.to_datetime(df["calendar_date"]).dt.strftime("%Y-%m-%d")

    # Round numeric columns.
    for col in df.columns:
        if col in _RATIO_COLUMNS:
            df[col] = df[col].round(_RATIO_DECIMALS)
        elif col not in {"calendar_date", "reporting_currency"} and pd.api.types.is_numeric_dtype(
            df[col]
        ):
            df[col] = df[col].round(_MONEY_DECIMALS)

    return _serialize(df)


def _serialize(df: pd.DataFrame) -> bytes:
    """Serialize to CSV with human-readable headers and clean NULLs."""
    # Rename columns to human-readable headers.
    df = df.rename(columns=EXPORT_HEADERS)

    buffer = io.StringIO()
    # na_rep="" writes empty cells for NaN.
    # float_format=None so pandas uses each column's own representation
    # (rounding already applied above).
    df.to_csv(buffer, index=False, na_rep="", lineterminator="\n")
    return buffer.getvalue().encode("utf-8")
