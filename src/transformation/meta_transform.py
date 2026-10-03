"""Meta Ads transformation: raw canonical DataFrame -> typed, filtered,
currency-converted rows.

Input: DataFrame with canonical column names, all string values, produced by
       src.ingestion.meta_ads.ingest_meta_ads.
Output: DataFrame with typed values, multi-day intervals rejected, monetary
        columns in reporting currency.

Business decisions embedded here (confirmed in Phase 4 kickoff):
    1. Multi-day intervals are REJECTED. Meta's daily-grain export produces
       rows where reporting_start == reporting_end. Any row where they
       differ is an interval and cannot be assigned to a single day.
    2. Meta dates are used AS-IS, without timezone conversion. This assumes
       the ad account timezone matches settings.reporting_timezone. If they
       differ, daily attribution will be off by up to 24 hours.
    3. Null campaign_name is allowed and preserved as NA.
    4. Null impressions and link_clicks are allowed and preserved as NA.
"""

from __future__ import annotations

import pandas as pd
from config.settings import Settings
from src.fx.converter import convert_money_series
from src.transformation.cleaning import (
    normalize_campaign_series,
    parse_date_series,
    parse_money_series,
)
from src.utils.logging_config import get_logger
from src.validation.validators import DQReport

log = get_logger(__name__)


def transform_meta_ads(
    df: pd.DataFrame,
    *,
    settings: Settings,
    report: DQReport,
) -> tuple[pd.DataFrame, DQReport]:
    """Apply Meta Ads business logic to a canonically-mapped DataFrame.

    Mutates `report` in place to accumulate rejection counts. Returns a new
    DataFrame; the input is not modified.
    """
    out = df.copy()

    # ------------------------------------------------------------------ #
    # Report bookkeeping                                                  #
    # ------------------------------------------------------------------ #
    # See transform_shopify for the rationale: if the report has a stale
    # rows_received (e.g., when called standalone in tests), use the actual
    # input row count.
    if report.rows_received < len(df):
        report.rows_received = len(df)

    # ------------------------------------------------------------------ #
    # 1. Parse reporting_start and reporting_end as dates.               #
    # ------------------------------------------------------------------ #
    out["reporting_start_d"] = parse_date_series(out["reporting_start"])
    out["reporting_end_d"] = parse_date_series(out["reporting_end"])

    invalid_date_mask = out["reporting_start_d"].isna() | out["reporting_end_d"].isna()
    n_invalid_date = int(invalid_date_mask.sum())
    if n_invalid_date:
        report.add_rejection("invalid_meta_date", n_invalid_date)
        out = out.loc[~invalid_date_mask].copy()

    # ------------------------------------------------------------------ #
    # 2. Reject multi-day intervals.                                      #
    # ------------------------------------------------------------------ #
    multi_day_mask = out["reporting_start_d"] != out["reporting_end_d"]
    n_multi_day = int(multi_day_mask.sum())
    if n_multi_day:
        sample_starts = out.loc[multi_day_mask, "reporting_start_d"].astype(str).head(3).tolist()
        log.warning(
            "Rejecting %d multi-day Meta intervals. Re-export at daily granularity.",
            n_multi_day,
            extra={
                "context": {
                    "count": n_multi_day,
                    "example_starts": sample_starts,
                }
            },
        )
        report.add_rejection("multi_day_interval", n_multi_day)
        out = out.loc[~multi_day_mask].copy()

    out["calendar_date"] = out["reporting_start_d"]

    # ------------------------------------------------------------------ #
    # 3. Parse spend_amount (required).                                   #
    # ------------------------------------------------------------------ #
    out["spend_amount"] = parse_money_series(out["spend_amount"])
    invalid_spend_mask = out["spend_amount"].isna()
    n_invalid_spend = int(invalid_spend_mask.sum())
    if n_invalid_spend:
        report.add_rejection("invalid_spend", n_invalid_spend)
        out = out.loc[~invalid_spend_mask].copy()

    # ------------------------------------------------------------------ #
    # 4. Parse optional numeric columns.                                  #
    # ------------------------------------------------------------------ #
    if "impressions" in out.columns:
        out["impressions"] = pd.to_numeric(out["impressions"], errors="coerce").astype("Int64")

    if "link_clicks" in out.columns:
        out["link_clicks"] = pd.to_numeric(out["link_clicks"], errors="coerce").astype("Int64")

    # ------------------------------------------------------------------ #
    # 5. Normalize campaign_name.                                         #
    # ------------------------------------------------------------------ #
    if "campaign_name" in out.columns:
        out["campaign_name"] = normalize_campaign_series(out["campaign_name"])

    # ------------------------------------------------------------------ #
    # 6. Convert spend to reporting currency.                             #
    # ------------------------------------------------------------------ #
    out["spend_amount"] = convert_money_series(
        out["spend_amount"],
        source_currency=settings.meta_source_currency,
        settings=settings,
    )

    # ------------------------------------------------------------------ #
    # 7. Add metadata, select final columns.                              #
    # ------------------------------------------------------------------ #
    out["reporting_currency"] = settings.reporting_currency

    final_columns = [
        "calendar_date",
        "campaign_name",
        "spend_amount",
        "impressions",
        "link_clicks",
        "reporting_currency",
    ]
    final_columns = [c for c in final_columns if c in out.columns]
    out = out[final_columns].reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # Report bookkeeping (final counts)                                   #
    # ------------------------------------------------------------------ #
    report.rows_accepted = len(out)
    report.rows_rejected = report.rows_received - len(out)

    log.info(
        "Meta transform complete",
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
