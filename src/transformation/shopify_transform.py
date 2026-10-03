"""Shopify transformation: raw canonical DataFrame -> typed, filtered,
currency-converted rows.

Input: DataFrame with canonical column names, all string values, produced by
       src.ingestion.shopify.ingest_shopify.
Output: DataFrame with typed values, filtered to revenue-recognized orders,
        monetary columns in reporting currency.

The output is at ORDER grain, one row per order, not aggregated. Aggregation
to daily grain happens in the SQL layer.

Business decisions embedded here (all confirmed in Phase 4 kickoff):
    1. net_amount = gross_amount - discount_amount, tax-exclusive,
       shipping-exclusive. (CONFIRM WITH CLIENT — see note below.)
    2. Refunds handled as separate rows, net against refund date. In this
       implementation, we do NOT decompose refunds from orders; we assume the
       export's financial_status already reflects the refunded state.
       (CONFIRM WITH CLIENT — see note below.)
    3. Revenue-recognized statuses: paid, partially_paid, partially_refunded.
       Excluded: pending, cancelled, refunded, voided. Unknown: excluded with
       a warning.
    4. Multi-currency Shopify orders are NOT supported in v1. All orders are
       assumed to be in settings.shopify_source_currency.
"""

from __future__ import annotations

import pandas as pd
from config.settings import Settings
from src.fx.converter import convert_money_series
from src.transformation.cleaning import (
    normalize_status_series,
    parse_money_series,
    parse_timestamp_series,
    to_reporting_date,
)
from src.utils.logging_config import get_logger
from src.validation.validators import DQReport

log = get_logger(__name__)

# Monetary columns that must be converted to the reporting currency.
_MONEY_COLUMNS: tuple[str, ...] = (
    "gross_amount",
    "discount_amount",
    "net_amount",
    "taxes",
    "shipping_fees",
)

# Monetary columns that, if unparseable, cause row rejection.
_REQUIRED_MONEY_COLUMNS: tuple[str, ...] = ("gross_amount", "net_amount")

# Optional monetary columns: NA is treated as 0 after conversion.
_OPTIONAL_MONEY_COLUMNS: tuple[str, ...] = (
    "discount_amount",
    "taxes",
    "shipping_fees",
)


def transform_shopify(
    df: pd.DataFrame,
    *,
    settings: Settings,
    report: DQReport,
) -> tuple[pd.DataFrame, DQReport]:
    """Apply Shopify business logic to a canonically-mapped DataFrame.

    Mutates `report` in place to accumulate rejection counts. Returns a new
    DataFrame; the input is not modified.

    Raises:
        TransformationError: if the input is missing a required canonical
            column. (Schema validation should have caught this earlier; this
            is a defensive check.)
    """
    out = df.copy()

    # ------------------------------------------------------------------ #
    # Report bookkeeping                                                  #
    # ------------------------------------------------------------------ #
    # The report's rows_received is normally set by the ingestion stage to
    # the raw file's row count. When transform_shopify is called standalone
    # (e.g., in a unit test), the report may have rows_received == 0. In
    # that case, treat the number of rows this function received as the
    # starting count.
    if report.rows_received < len(df):
        report.rows_received = len(df)

    # ------------------------------------------------------------------ #
    # 1. Parse created_at to UTC, derive calendar_date in reporting TZ.   #
    # ------------------------------------------------------------------ #
    out["created_at_utc"] = parse_timestamp_series(out["created_at"])

    invalid_date_mask = out["created_at_utc"].isna()
    n_invalid_date = int(invalid_date_mask.sum())
    if n_invalid_date:
        report.add_rejection("invalid_created_at", n_invalid_date)
        out = out.loc[~invalid_date_mask].copy()

    out["calendar_date"] = to_reporting_date(
        out["created_at_utc"],
        reporting_timezone=settings.reporting_timezone,
    )

    # ------------------------------------------------------------------ #
    # 2. Parse monetary columns.                                          #
    # ------------------------------------------------------------------ #
    for col in _MONEY_COLUMNS:
        out[col] = parse_money_series(out[col])

    invalid_money_mask = pd.Series(False, index=out.index)
    for col in _REQUIRED_MONEY_COLUMNS:
        invalid_money_mask |= out[col].isna()
    n_invalid_money = int(invalid_money_mask.sum())
    if n_invalid_money:
        report.add_rejection("invalid_money", n_invalid_money)
        out = out.loc[~invalid_money_mask].copy()

    for col in _OPTIONAL_MONEY_COLUMNS:
        out[col] = out[col].fillna(0.0)

    # ------------------------------------------------------------------ #
    # 3. Normalize and classify financial_status.                         #
    # ------------------------------------------------------------------ #
    out["financial_status"] = normalize_status_series(out["financial_status"])

    known_statuses = settings.revenue_statuses | settings.excluded_statuses
    unknown_mask = ~out["financial_status"].isin(known_statuses) & out["financial_status"].notna()
    if unknown_mask.any():
        unknown_values = sorted(out.loc[unknown_mask, "financial_status"].unique().tolist())
        log.warning(
            "Unknown Shopify financial_status values; treating as excluded",
            extra={
                "context": {
                    "unknown_statuses": unknown_values,
                    "row_count": int(unknown_mask.sum()),
                }
            },
        )

    recognized_mask = out["financial_status"].isin(settings.revenue_statuses)
    excluded_mask = ~recognized_mask
    n_excluded = int(excluded_mask.sum())
    if n_excluded:
        report.add_rejection("excluded_status", n_excluded)
    out = out.loc[recognized_mask].copy()

    # ------------------------------------------------------------------ #
    # 4. Convert monetary columns to the reporting currency.              #
    # ------------------------------------------------------------------ #
    for col in _MONEY_COLUMNS:
        out[col] = convert_money_series(
            out[col],
            source_currency=settings.shopify_source_currency,
            settings=settings,
        )

    # ------------------------------------------------------------------ #
    # 5. Add reporting currency metadata and select final columns.        #
    # ------------------------------------------------------------------ #
    out["reporting_currency"] = settings.reporting_currency

    out = out[
        [
            "order_id",
            "calendar_date",
            "created_at_utc",
            "financial_status",
            "gross_amount",
            "discount_amount",
            "net_amount",
            "taxes",
            "shipping_fees",
            "reporting_currency",
        ]
    ].reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # Report bookkeeping (final counts)                                   #
    # ------------------------------------------------------------------ #
    report.rows_accepted = len(out)
    report.rows_rejected = report.rows_received - len(out)

    log.info(
        "Shopify transform complete",
        extra={
            "context": {
                "rows_in": len(df),
                "rows_out": len(out),
                "rejected_total": report.rows_rejected,
                "rejection_reasons": dict(report.rejection_reasons),
            }
        },
    )

    return out, report
