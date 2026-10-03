"""The end-to-end pipeline orchestrator.

Takes raw Shopify and Meta CSVs and produces the daily_financial_model table
in DuckDB. Returns a structured PipelineResult describing what happened.

Responsibilities:
    - Ingest both sources (read + map headers + validate).
    - Transform both sources (parse + classify + convert currency).
    - Load cleaned data into DuckDB.
    - Execute the SQL model.
    - Enforce the data-quality rejection threshold.
    - Return a PipelineResult with the summary info the CLI needs.

Non-responsibilities:
    - Argument parsing (that's cli.py).
    - Output formatting (that's cli.py).
    - Streamlit concerns (that's app.py in Phase 8).
    - Writing to disk outside of DuckDB (that's reporting/export.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
from config.settings import Settings

from src.database.duckdb_engine import (
    close_database,
    execute_sql_directory,
    load_dataframe,
    open_database,
)
from src.ingestion.meta_ads import ingest_meta_ads
from src.ingestion.shopify import ingest_shopify
from src.transformation.meta_transform import transform_meta_ads
from src.transformation.shopify_transform import transform_shopify
from src.utils.logging_config import get_logger
from src.validation.validators import DQReport, check_rejection_threshold

log = get_logger(__name__)


@dataclass
class PipelineResult:
    """The outcome of a single pipeline run.

    This is the contract between the pipeline and its callers (CLI, Streamlit,
    tests). Everything a caller needs to display or decide on is here; nothing
    that requires re-querying the database.
    """

    shopify_report: DQReport
    meta_report: DQReport
    database_path: Path
    sql_dir: Path
    dates_min: str | None
    dates_max: str | None
    total_net_revenue: float
    total_ad_spend: float
    total_contribution_margin: float
    currency: str


def _derive_summary(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Query the model for the totals the CLI displays.

    Aggregates live in the model; the pipeline does not recompute them.
    """
    result = conn.execute("""
        SELECT
            MIN(calendar_date) AS min_date,
            MAX(calendar_date) AS max_date,
            SUM(net_revenue) AS total_net_revenue,
            SUM(ad_spend) AS total_ad_spend,
            SUM(contribution_margin) AS total_contribution_margin,
            MAX(reporting_currency) AS currency
        FROM daily_financial_model
    """).fetchone()

    if result is None:
        return {
            "dates_min": None,
            "dates_max": None,
            "total_net_revenue": 0.0,
            "total_ad_spend": 0.0,
            "total_contribution_margin": 0.0,
            "currency": "?",
        }

    min_date, max_date, net_rev, ad_spend, contribution, currency = result
    return {
        "dates_min": min_date.isoformat() if min_date else None,
        "dates_max": max_date.isoformat() if max_date else None,
        "total_net_revenue": float(net_rev or 0.0),
        "total_ad_spend": float(ad_spend or 0.0),
        "total_contribution_margin": float(contribution or 0.0),
        "currency": currency or "?",
    }


def run_pipeline(
    *,
    shopify_csv: Path,
    meta_csv: Path,
    settings: Settings,
    sql_dir: Path,
) -> PipelineResult:
    """Execute the full pipeline.

    Args:
        shopify_csv: Path to the raw Shopify export.
        meta_csv: Path to the raw Meta Ads export.
        settings: Validated application settings.
        sql_dir: Directory containing the numbered SQL files.

    Returns:
        PipelineResult with data-quality reports and summary statistics.

    Raises:
        SchemaError: on fatal file/schema problems.
        DataQualityError: if row rejection exceeds the configured threshold.
        TransformationError: on unexpected transformation failures.
        DatabaseError: on DuckDB failures.
    """
    log.info(
        "Pipeline started",
        extra={
            "context": {
                "shopify_csv": str(shopify_csv),
                "meta_csv": str(meta_csv),
                "database": str(settings.database_path),
                "sql_dir": str(sql_dir),
                "reporting_currency": settings.reporting_currency,
                "reporting_timezone": settings.reporting_timezone,
            }
        },
    )

    # ------------------------------------------------------------------ #
    # 1. INGEST                                                            #
    # ------------------------------------------------------------------ #
    log.info("Stage 1/5: ingesting sources")

    shopify_ingest, _ = ingest_shopify(shopify_csv)
    meta_ingest, _ = ingest_meta_ads(meta_csv)

    # ------------------------------------------------------------------ #
    # 2. ENFORCE REJECTION THRESHOLDS                                      #
    # ------------------------------------------------------------------ #
    # We check AFTER ingestion but BEFORE transformation. If the input is
    # garbage, we want to stop before running expensive transforms.
    check_rejection_threshold(
        shopify_ingest.report, threshold=float(settings.dq_rejection_threshold)
    )
    check_rejection_threshold(meta_ingest.report, threshold=float(settings.dq_rejection_threshold))

    # ------------------------------------------------------------------ #
    # 3. TRANSFORM                                                         #
    # ------------------------------------------------------------------ #
    log.info("Stage 2/5: transforming sources")

    shopify_clean, _ = transform_shopify(
        shopify_ingest.accepted,
        settings=settings,
        report=shopify_ingest.report,
    )
    meta_clean, _ = transform_meta_ads(
        meta_ingest.accepted,
        settings=settings,
        report=meta_ingest.report,
    )

    # ------------------------------------------------------------------ #
    # 4. LOAD + MODEL                                                      #
    # ------------------------------------------------------------------ #
    log.info("Stage 3/5: loading into DuckDB")

    conn = open_database(settings.database_path)
    try:
        load_dataframe(conn, shopify_clean, "shopify_orders_clean")
        load_dataframe(conn, meta_clean, "meta_ads_clean")

        # Inject business parameters as session variables for the SQL model.
        conn.execute(
            "SET VARIABLE cogs_percentage = ?;",
            [float(settings.cogs_percentage)],
        )

        log.info("Stage 4/5: executing SQL model")
        execute_sql_directory(conn, sql_dir)

        log.info("Stage 5/5: computing summary")
        summary = _derive_summary(conn)
    finally:
        close_database(conn)

    result = PipelineResult(
        shopify_report=shopify_ingest.report,
        meta_report=meta_ingest.report,
        database_path=settings.database_path,
        sql_dir=sql_dir,
        dates_min=summary["dates_min"],  # type: ignore[arg-type]
        dates_max=summary["dates_max"],  # type: ignore[arg-type]
        total_net_revenue=summary["total_net_revenue"],  # type: ignore[arg-type]
        total_ad_spend=summary["total_ad_spend"],  # type: ignore[arg-type]
        total_contribution_margin=summary["total_contribution_margin"],  # type: ignore[arg-type]
        currency=summary["currency"],  # type: ignore[arg-type]
    )

    log.info(
        "Pipeline completed",
        extra={
            "context": {
                "dates": f"{result.dates_min}..{result.dates_max}",
                "total_net_revenue": result.total_net_revenue,
                "total_ad_spend": result.total_ad_spend,
                "currency": result.currency,
                "shopify_rejected": result.shopify_report.rows_rejected,
                "meta_rejected": result.meta_report.rows_rejected,
            }
        },
    )

    return result
