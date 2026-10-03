"""Tests for src/reporting/dashboard_data.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from config.settings import Settings
from src.database.duckdb_engine import (
    close_database,
    execute_sql_directory,
    load_dataframe,
    open_database,
)
from src.reporting.dashboard_data import (
    DASHBOARD_COLUMNS,
    get_date_range,
    load_model,
    model_exists,
)

FIXTURES = Path(__file__).parent / "fixtures"
SQL_DIR = Path(__file__).parent.parent / "sql"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "dash.duckdb",
        raw_data_dir=tmp_path / "raw",
        log_dir=tmp_path / "logs",
    )


def _populate_model(db_path: Path, sql_dir: Path) -> None:
    """Load the golden fixtures into the model at db_path."""
    from src.ingestion.meta_ads import ingest_meta_ads
    from src.ingestion.shopify import ingest_shopify
    from src.transformation.meta_transform import transform_meta_ads
    from src.transformation.shopify_transform import transform_shopify
    from src.validation.validators import DQReport

    settings = Settings(
        database_path=db_path,
        reporting_currency="ETB",
        reporting_timezone="Africa/Addis_Ababa",
        shopify_source_currency="ETB",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("130.0"),
        etb_to_reporting_fx_rate=Decimal("1.0"),
        cogs_percentage=Decimal("0.40"),
    )

    shopify_result, _ = ingest_shopify(FIXTURES / "golden_shopify.csv")
    meta_result, _ = ingest_meta_ads(FIXTURES / "golden_meta.csv")

    shopify_clean, _ = transform_shopify(
        shopify_result.accepted,
        settings=settings,
        report=DQReport(source="shopify"),
    )
    meta_clean, _ = transform_meta_ads(
        meta_result.accepted,
        settings=settings,
        report=DQReport(source="meta_ads"),
    )

    conn = open_database(db_path)
    try:
        load_dataframe(conn, shopify_clean, "shopify_orders_clean")
        load_dataframe(conn, meta_clean, "meta_ads_clean")
        conn.execute("SET VARIABLE cogs_percentage = 0.40;")
        execute_sql_directory(conn, sql_dir)
    finally:
        close_database(conn)


# ---------------------------------------------------------------------- #
# model_exists                                                            #
# ---------------------------------------------------------------------- #


def test_model_exists_false_when_no_database(tmp_path: Path) -> None:
    assert not model_exists(_settings(tmp_path))


def test_model_exists_true_after_populating(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _populate_model(settings.database_path, SQL_DIR)
    assert model_exists(settings)


# ---------------------------------------------------------------------- #
# load_model                                                              #
# ---------------------------------------------------------------------- #


def test_load_model_returns_all_dates(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _populate_model(settings.database_path, SQL_DIR)
    df = load_model(settings=settings)
    assert len(df) == 5
    assert list(df.columns) == list(DASHBOARD_COLUMNS)


def test_load_model_filtered_by_date(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _populate_model(settings.database_path, SQL_DIR)
    df = load_model(
        settings=settings,
        date_from=date(2026, 9, 2),
        date_to=date(2026, 9, 4),
    )
    dates = [ts.date() for ts in df["calendar_date"]]
    assert dates == [date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)]


def test_load_model_empty_range(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _populate_model(settings.database_path, SQL_DIR)
    df = load_model(
        settings=settings,
        date_from=date(2030, 1, 1),
        date_to=date(2030, 1, 2),
    )
    assert df.empty


# ---------------------------------------------------------------------- #
# get_date_range                                                          #
# ---------------------------------------------------------------------- #


def test_get_date_range_on_empty_model(tmp_path: Path) -> None:
    # No database at all.
    assert get_date_range(_settings(tmp_path)) is None


def test_get_date_range_from_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _populate_model(settings.database_path, SQL_DIR)
    result = get_date_range(settings)
    assert result == (date(2026, 9, 1), date(2026, 9, 5))
