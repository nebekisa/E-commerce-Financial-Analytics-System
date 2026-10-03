"""Tests for src/pipeline.py.

The orchestrator is tested with the golden dataset so the numbers are
hand-verifiable. These tests are integration tests: they run ingest, transform,
load, and model in one call.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from config.settings import Settings
from src.exceptions import DataQualityError, SchemaError
from src.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
SQL_DIR = Path(__file__).parent.parent / "sql"


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    defaults = dict(
        database_path=tmp_path / "pipeline.duckdb",
        raw_data_dir=tmp_path / "raw",
        log_dir=tmp_path / "logs",
        reporting_currency="ETB",
        reporting_timezone="Africa/Addis_Ababa",
        shopify_source_currency="ETB",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("130.0"),
        etb_to_reporting_fx_rate=Decimal("1.0"),
        cogs_percentage=Decimal("0.40"),
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_run_pipeline_on_golden_dataset(tmp_path: Path) -> None:
    """End-to-end: golden fixtures -> PipelineResult with hand-computed totals.

    Totals across the 5-day golden dataset:
        net_revenue           = 3580.0 ETB
        ad_spend              = 19500.0 ETB
        contribution_margin   = -17440.0 ETB
        date range            = 2026-09-01 .. 2026-09-05
    """
    result = run_pipeline(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        settings=_settings(tmp_path),
        sql_dir=SQL_DIR,
    )

    assert result.dates_min == "2026-09-01"
    assert result.dates_max == "2026-09-05"
    assert result.total_net_revenue == pytest.approx(3580.0)
    assert result.total_ad_spend == pytest.approx(19500.0)
    assert result.total_contribution_margin == pytest.approx(-17440.0)
    assert result.currency == "ETB"


def test_run_pipeline_records_rejections(tmp_path: Path) -> None:
    """The pipeline's DQReport must reflect transform-stage rejections.

    Golden Shopify has 8 rows; 2 are excluded (cancelled, refunded).
    Golden Meta has 5 rows; 0 are rejected.
    """
    result = run_pipeline(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        settings=_settings(tmp_path),
        sql_dir=SQL_DIR,
    )

    assert result.shopify_report.rows_received == 8
    assert result.shopify_report.rejection_reasons.get("excluded_status") == 2
    assert result.meta_report.rows_received == 5
    assert result.meta_report.rows_rejected == 0


def test_run_pipeline_is_idempotent(tmp_path: Path) -> None:
    """Running twice on the same inputs produces the same result."""
    settings = _settings(tmp_path)
    r1 = run_pipeline(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        settings=settings,
        sql_dir=SQL_DIR,
    )
    r2 = run_pipeline(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        settings=settings,
        sql_dir=SQL_DIR,
    )
    assert r1.total_net_revenue == r2.total_net_revenue
    assert r1.total_ad_spend == r2.total_ad_spend


def test_run_pipeline_missing_shopify_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        run_pipeline(
            shopify_csv=tmp_path / "nope.csv",
            meta_csv=FIXTURES / "golden_meta.csv",
            settings=_settings(tmp_path),
            sql_dir=SQL_DIR,
        )


def test_run_pipeline_rejects_high_rejection_rate(tmp_path: Path) -> None:
    """A file with a very high rejection rate should abort with DataQualityError."""
    # The dirty Shopify fixture has 4 rejections out of 10 rows = 40% rejection.
    # Set the threshold below that to force a failure.
    settings = _settings(tmp_path, dq_rejection_threshold=Decimal("0.10"))
    with pytest.raises(DataQualityError):
        run_pipeline(
            shopify_csv=FIXTURES / "shopify_dirty.csv",
            meta_csv=FIXTURES / "golden_meta.csv",
            settings=settings,
            sql_dir=SQL_DIR,
        )


def test_run_pipeline_tolerates_high_rejection_when_threshold_allows(
    tmp_path: Path,
) -> None:
    """Same dirty file, but a threshold of 1.0 means never fail."""
    settings = _settings(tmp_path, dq_rejection_threshold=Decimal("1.0"))
    result = run_pipeline(
        shopify_csv=FIXTURES / "shopify_dirty.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        settings=settings,
        sql_dir=SQL_DIR,
    )
    # Dirty fixture has 4 rejections; pipeline should complete.
    assert result.shopify_report.rows_rejected > 0
