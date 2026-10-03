"""Command-line interface for the pipeline.

Usage:
    python -m src --shopify data/raw/shopify.csv --meta data/raw/meta.csv

The CLI parses arguments, configures logging, calls the pipeline, prints a
summary, and returns an exit code. It contains NO data-processing logic.
"""

from __future__ import annotations

import argparse
import argparse
import contextlib
import sys
from pathlib import Path

from config.settings import Settings

from src.exceptions import (
    ConfigurationError,
    CurrencyError,
    DatabaseError,
    DataQualityError,
    PipelineError,
    SchemaError,
    TransformationError,
)
from src.pipeline import PipelineResult, run_pipeline
from src.utils.logging_config import configure_logging, get_logger

# ---------------------------------------------------------------------- #
# Exit codes                                                              #
#                                                                         #
# Non-zero for all failures. Distinct values let scripts and schedulers   #
# branch on the failure class without parsing stderr.                     #
# ---------------------------------------------------------------------- #

_EXIT_OK = 0
_EXIT_SCHEMA = 2
_EXIT_DATA_QUALITY = 3
_EXIT_CURRENCY = 4
_EXIT_DATABASE = 5
_EXIT_TRANSFORMATION = 6
_EXIT_CONFIGURATION = 7
_EXIT_UNKNOWN = 99


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecommerce-financial-analytics",
        description=(
            "Run the Shopify + Meta Ads financial analytics pipeline. "
            "Reads raw CSVs, produces a DuckDB daily financial model."
        ),
    )
    parser.add_argument(
        "--shopify",
        type=Path,
        required=True,
        help="Path to the raw Shopify CSV export.",
    )
    parser.add_argument(
        "--meta",
        type=Path,
        required=True,
        help="Path to the raw Meta Ads CSV export.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Path to the DuckDB file (default: from settings).",
    )
    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=Path("sql"),
        help="Directory containing numbered .sql files (default: ./sql).",
    )
    parser.add_argument(
        "--reporting-currency",
        type=str,
        default=None,
        help="ISO 4217 reporting currency (default: from settings).",
    )
    parser.add_argument(
        "--fx-rate",
        type=str,
        default=None,
        help="USD→reporting-currency FX rate (default: from settings).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Logging level (default: from settings).",
    )
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Build a Settings object from parsed CLI arguments, with defaults."""
    overrides: dict[str, object] = {}
    if args.database is not None:
        overrides["database_path"] = args.database
    if args.reporting_currency is not None:
        overrides["reporting_currency"] = args.reporting_currency
    if args.fx_rate is not None:
        from decimal import Decimal

        overrides["usd_to_reporting_fx_rate"] = Decimal(args.fx_rate)
    return Settings(**overrides)  # type: ignore[arg-type]


def _print_summary(result: PipelineResult) -> None:
    """Print a human-readable summary to stdout.

    This is what the user sees. It must be scannable at a glance:
    - what was processed
    - what the totals were
    - where the output lives
    - what warnings or rejections occurred

    IMPORTANT: only ASCII characters are emitted. stdout's encoding is
    environment-dependent (cp1252 on default Windows, UTF-8 elsewhere),
    and non-ASCII characters raise UnicodeEncodeError on non-UTF-8
    terminals. If future changes need Unicode, call `_ensure_utf8_stdout`
    at the top of `main()` first.
    """
    print()
    print("=" * 72)
    print("  FINANCIAL ANALYTICS PIPELINE -- SUMMARY")
    print("=" * 72)

    if result.dates_min and result.dates_max:
        print(f"  Date range:              {result.dates_min} .. {result.dates_max}")
    else:
        print("  Date range:              (no data)")

    print(f"  Reporting currency:      {result.currency}")
    print()

    print(f"  Shopify rows received:   {result.shopify_report.rows_received}")
    print(f"  Shopify rows accepted:   {result.shopify_report.rows_accepted}")
    print(f"  Shopify rows rejected:   {result.shopify_report.rows_rejected}")
    if result.shopify_report.rejection_reasons:
        for reason, count in sorted(result.shopify_report.rejection_reasons.items()):
            print(f"      - {reason}: {count}")
    print()

    print(f"  Meta rows received:      {result.meta_report.rows_received}")
    print(f"  Meta rows accepted:      {result.meta_report.rows_accepted}")
    print(f"  Meta rows rejected:      {result.meta_report.rows_rejected}")
    if result.meta_report.rejection_reasons:
        for reason, count in sorted(result.meta_report.rejection_reasons.items()):
            print(f"      - {reason}: {count}")
    print()

    print(f"  Total net revenue:       {result.total_net_revenue:,.2f} {result.currency}")
    print(f"  Total ad spend:          {result.total_ad_spend:,.2f} {result.currency}")
    print(f"  Contribution margin:     {result.total_contribution_margin:,.2f} {result.currency}")
    print()

    print(f"  Database:                {result.database_path}")
    print("  Model table:             daily_financial_model")
    print("=" * 72)
    print()


def _ensure_utf8_stdout() -> None:
    """Force stdout and stderr to UTF-8 regardless of platform default.

    On Windows, the default stdout encoding is often cp1252 or another
    locale-specific codepage. Any non-ASCII output would raise
    UnicodeEncodeError. This function makes the streams UTF-8 so that
    Unicode output is always safe.

    Idempotent. Safe to call multiple times. No-op if the streams do not
    support reconfigure (e.g., already-closed streams).
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8")

def _exit_code_for(exc: PipelineError) -> int:
    if isinstance(exc, SchemaError):
        return _EXIT_SCHEMA
    if isinstance(exc, DataQualityError):
        return _EXIT_DATA_QUALITY
    if isinstance(exc, CurrencyError):
        return _EXIT_CURRENCY
    if isinstance(exc, DatabaseError):
        return _EXIT_DATABASE
    if isinstance(exc, TransformationError):
        return _EXIT_TRANSFORMATION
    if isinstance(exc, ConfigurationError):
        return _EXIT_CONFIGURATION
    return _EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns an exit code (0 = success)."""
    _ensure_utf8_stdout()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        settings = _settings_from_args(args)
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return _EXIT_CONFIGURATION

    # Configure logging before anything else, using the resolved log level.
    configure_logging(
        level=args.log_level or settings.log_level,
        log_dir=settings.log_dir,
    )
    log = get_logger("cli")

    try:
        result = run_pipeline(
            shopify_csv=args.shopify,
            meta_csv=args.meta,
            settings=settings,
            sql_dir=args.sql_dir,
        )
    except PipelineError as exc:
        log.error(
            "Pipeline failed: %s",
            exc,
            extra={"context": {"error_type": type(exc).__name__, **exc.context}},
        )
        print(f"\nError: {exc}", file=sys.stderr)
        return _exit_code_for(exc)
    except Exception as exc:
        # Last-resort catch: anything not already a PipelineError is a bug.
        # Log the full traceback; the CLI shows a generic message.
        log.exception("Unexpected error during pipeline execution")
        print(
            f"\nUnexpected error: {type(exc).__name__}: {exc}\nSee logs for details.",
            file=sys.stderr,
        )
        return _EXIT_UNKNOWN

    _print_summary(result)
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
