"""Smoke tests for app.py using Streamlit's AppTest.

These tests verify:
    - The app boots without raising.
    - The upload widgets render.
    - The Run button is disabled when files are missing.
    - The KPI ribbon renders after a pipeline run.
    - The download button is present.

What these tests do NOT verify:
    - Chart rendering (AppTest cannot inspect chart output).
    - Colors or styling.
    - Download button payload correctness (that's test_export.py).

Environment note:
    Streamlit's st.line_chart internally calls into altair. Recent altair
    versions (5.5+) deprecate APIs that the current Streamlit release still
    uses. Those deprecations surface as warnings; under pytest's strict
    warning filter they would fail tests. We scope the strict filter to
    our own modules in pyproject.toml and suppress altair/streamlit
    deprecations locally.
"""

from __future__ import annotations

import warnings
from decimal import Decimal
from pathlib import Path

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
from src.validation.validators import DQReport
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent.parent / "app.py"
FIXTURES = Path(__file__).parent / "fixtures"
SQL_DIR = Path(__file__).parent.parent / "sql"


def _fresh_app() -> AppTest:
    """Instantiate AppTest with a reasonable timeout and suppressed
    third-party deprecation warnings.

    The default timeout is 3 seconds, which is too short for a first run
    that has to import pandas, duckdb, streamlit, and plotly. 10 seconds is
    generous for a cold start.

    Warnings from altair and streamlit internals are ignored. They reflect
    upstream library churn, not bugs in our code, and are outside our
    control.
    """
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"altair.*",
    )
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"streamlit.*",
    )
    return AppTest.from_file(str(APP_PATH), default_timeout=10)


def _build_golden_db(db_path: Path) -> None:
    """Populate a DuckDB at db_path with the golden dataset."""
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
        execute_sql_directory(conn, SQL_DIR)
    finally:
        close_database(conn)


def _golden_settings(db_path: Path) -> Settings:
    """Settings pointed at a pre-populated DB, with the golden config."""
    return Settings(
        database_path=db_path,
        reporting_currency="ETB",
        reporting_timezone="Africa/Addis_Ababa",
        shopify_source_currency="ETB",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("130.0"),
        etb_to_reporting_fx_rate=Decimal("1.0"),
        cogs_percentage=Decimal("0.40"),
    )


# ---------------------------------------------------------------------- #
# Boot                                                                    #
# ---------------------------------------------------------------------- #


def test_app_boots_without_error() -> None:
    """The app renders without raising an unhandled exception."""
    at = _fresh_app()
    at.run()
    assert not at.exception, f"App raised: {at.exception}"


def test_app_shows_title_and_caption() -> None:
    """st.title registers as at.title, not at.markdown."""
    at = _fresh_app()
    at.run()
    assert any(
        "E-commerce Financial Analytics" in t.value for t in at.title
    ), f"Titles found: {[t.value for t in at.title]}"


# ---------------------------------------------------------------------- #
# Upload widgets                                                          #
# ---------------------------------------------------------------------- #


def test_app_renders_one_run_button() -> None:
    at = _fresh_app()
    at.run()
    assert len(at.button) == 1


def test_run_button_disabled_without_files() -> None:
    at = _fresh_app()
    at.run()
    button = at.button[0]
    assert "Run Financial Analysis" in button.label
    assert button.disabled is True


def test_app_shows_upload_prompt_before_run() -> None:
    """Before any upload, the app should show the 'upload both files' info box."""
    at = _fresh_app()
    at.run()
    info_messages = [i.value for i in at.info]
    assert any("Upload both files" in msg for msg in info_messages)


# ---------------------------------------------------------------------- #
# Post-run (populated DB, session state pre-set)                          #
# ---------------------------------------------------------------------- #


def test_app_shows_kpi_ribbon_with_populated_db(tmp_path: Path) -> None:
    """Given a populated DuckDB and pipeline_ran=True, the ribbon renders."""
    db_path = tmp_path / "app_test.duckdb"
    _build_golden_db(db_path)

    at = _fresh_app()
    at.session_state["settings"] = _golden_settings(db_path)
    at.session_state["pipeline_ran"] = True
    at.run()

    assert not at.exception, f"App raised: {at.exception}"

    metric_labels = [m.label for m in at.metric]
    assert "Estimated Contribution Margin" in metric_labels
    assert "Blended ROAS" in metric_labels
    assert "Total Net Revenue" in metric_labels
    assert "Orders" in metric_labels

    net_revenue_metric = next(m for m in at.metric if m.label == "Total Net Revenue")
    assert "3,580" in net_revenue_metric.value


def test_app_shows_download_button_with_populated_db(tmp_path: Path) -> None:
    """The download button renders once the ribbon is visible."""
    db_path = tmp_path / "app_test_dl.duckdb"
    _build_golden_db(db_path)

    at = _fresh_app()
    at.session_state["settings"] = _golden_settings(db_path)
    at.session_state["pipeline_ran"] = True
    at.run()

    assert not at.exception
    download_buttons = at.get("download_button")
    assert len(download_buttons) == 1
    assert "Download daily model" in download_buttons[0].label
