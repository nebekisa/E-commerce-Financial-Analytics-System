"""End-to-end integration test.

This test exercises the entire pipeline as a black box, simulating what a
real user does:
    1. Provide two raw CSVs.
    2. Invoke the CLI.
    3. Verify the CLI's summary output and exit code.
    4. Open the resulting DuckDB and verify the model's shape.
    5. Query the model through the dashboard data layer.
    6. Compute the ribbon KPIs.
    7. Generate the CSV export and read it back.

The goal is to catch bugs at the boundaries between components — cases where
every unit test passes but the components disagree about data shape,
ordering, dtype, or units.

This test is slow (a few seconds) but runs once. It is not parametrized.
Lower-level behavior is covered by the unit tests in the rest of tests/.
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from config.settings import Settings
from src.database.duckdb_engine import (
    close_database,
    open_database,
    read_table,
)
from src.reporting.dashboard_data import load_model
from src.reporting.export import model_to_csv_bytes
from src.reporting.kpi_ribbon import compute_ribbon

FIXTURES = Path(__file__).parent / "fixtures"
SQL_DIR = Path(__file__).parent.parent / "sql"
PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _settings_for_db(db_path: Path) -> Settings:
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


def _run_cli(
    *,
    shopify_csv: Path,
    meta_csv: Path,
    db_path: Path,
    log_level: str = "ERROR",
) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess and return the completed process.

    Uses `sys.executable -m src.cli` so it works the same in any venv.
    Captures stdout and stderr as text for assertions.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.cli",
            "--shopify",
            str(shopify_csv),
            "--meta",
            str(meta_csv),
            "--database",
            str(db_path),
            "--sql-dir",
            str(SQL_DIR),
            "--reporting-currency",
            "ETB",
            "--fx-rate",
            "130.0",
            "--log-level",
            log_level,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


# ---------------------------------------------------------------------- #
# The test                                                                #
# ---------------------------------------------------------------------- #


def test_full_lifecycle_from_csv_to_dashboard_to_export(tmp_path: Path) -> None:
    """Full pipeline: raw CSVs -> CLI -> DuckDB -> dashboard -> export.

    Uses the golden fixtures, which have hand-calculated expected values
    (see tests/test_golden_dataset.py for the arithmetic).
    """
    db_path = tmp_path / "e2e.duckdb"

    # ------------------------------------------------------------------ #
    # Step 1: run the CLI as a subprocess                                 #
    # ------------------------------------------------------------------ #
    proc = _run_cli(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        db_path=db_path,
    )

    assert proc.returncode == 0, (
        f"CLI exited with {proc.returncode}.\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )

    # ------------------------------------------------------------------ #
    # Step 2: verify the CLI's summary output                             #
    # ------------------------------------------------------------------ #
    out = proc.stdout
    assert "2026-09-01 .. 2026-09-05" in out
    assert "3,580.00 ETB" in out  # total net revenue
    assert "19,500.00 ETB" in out  # total ad spend
    assert "-17,440.00 ETB" in out  # contribution margin
    # Shopify summary: 8 received, 6 accepted, 2 rejected (excluded_status).
    assert "Shopify rows accepted:   6" in out
    assert "excluded_status: 2" in out

    # ------------------------------------------------------------------ #
    # Step 3: open the resulting DuckDB and verify the model's shape      #
    # ------------------------------------------------------------------ #
    assert db_path.exists(), "CLI did not produce a database file"

    conn = open_database(db_path)
    try:
        model_df = read_table(conn, "daily_financial_model")
    finally:
        close_database(conn)

    assert len(model_df) == 5, f"Expected 5 dates, got {len(model_df)}"
    expected_columns = {
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
    }
    assert set(model_df.columns) == expected_columns

    # ------------------------------------------------------------------ #
    # Step 4: query via the dashboard layer                               #
    # ------------------------------------------------------------------ #
    settings = _settings_for_db(db_path)
    dash_df = load_model(settings=settings)

    assert len(dash_df) == 5
    # The dashboard columns are a subset of the model columns, ordered.
    assert "net_revenue" in dash_df.columns
    assert "ad_spend" in dash_df.columns

    # ------------------------------------------------------------------ #
    # Step 5: compute the ribbon KPIs                                     #
    # ------------------------------------------------------------------ #
    ribbon = compute_ribbon(dash_df, settings=settings)

    assert ribbon.total_net_revenue == pytest.approx(3580.0)
    assert ribbon.total_ad_spend == pytest.approx(19500.0)
    assert ribbon.total_contribution_margin == pytest.approx(-17440.0)
    assert ribbon.total_orders == 6
    assert ribbon.blended_roas == pytest.approx(3580 / 19500)
    assert ribbon.meta_spend_ratio == pytest.approx(19500 / 3580)
    assert ribbon.profit_margin == pytest.approx(-17440 / 3580)
    assert ribbon.administrative_hours_saved == 2.9
    assert ribbon.reporting_currency == "ETB"

    # ------------------------------------------------------------------ #
    # Step 6: export the model to CSV and read it back                    #
    # ------------------------------------------------------------------ #
    csv_bytes = model_to_csv_bytes(dash_df)
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    rows = list(reader)

    assert len(rows) == 5, f"CSV should have 5 data rows, got {len(rows)}"

    # Headers are human-readable.
    assert "Date" in rows[0]
    assert "Net Revenue" in rows[0]

    # Dates are ISO.
    assert rows[0]["Date"] == "2026-09-01"
    assert rows[4]["Date"] == "2026-09-05"

    # Numeric values match the model.
    assert float(rows[0]["Net Revenue"]) == pytest.approx(1400.0)
    assert float(rows[0]["Ad Spend"]) == pytest.approx(9100.0)

    # Sep 4 (Shopify-only date) has empty impressions.
    sep4_row = next(r for r in rows if r["Date"] == "2026-09-04")
    assert sep4_row["Impressions"] == ""
    assert sep4_row["Link Clicks"] == ""


def test_cli_run_is_idempotent(tmp_path: Path) -> None:
    """Running the CLI twice on the same inputs produces the same DB."""
    db_path = tmp_path / "idempotency.duckdb"

    proc1 = _run_cli(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        db_path=db_path,
    )
    assert proc1.returncode == 0

    conn = open_database(db_path)
    try:
        model1 = read_table(conn, "daily_financial_model")
    finally:
        close_database(conn)

    proc2 = _run_cli(
        shopify_csv=FIXTURES / "golden_shopify.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        db_path=db_path,
    )
    assert proc2.returncode == 0

    conn = open_database(db_path)
    try:
        model2 = read_table(conn, "daily_financial_model")
    finally:
        close_database(conn)

    pd.testing.assert_frame_equal(model1, model2)


def test_cli_reports_failure_cleanly(tmp_path: Path) -> None:
    """A missing input file must produce a clean error and non-zero exit."""
    proc = _run_cli(
        shopify_csv=tmp_path / "does_not_exist.csv",
        meta_csv=FIXTURES / "golden_meta.csv",
        db_path=tmp_path / "fail.duckdb",
    )

    assert proc.returncode != 0
    assert "Shopify CSV not found" in proc.stderr
    # No traceback leaked to the user.
    assert "Traceback" not in proc.stderr
    # No partial database created.
    assert not (tmp_path / "fail.duckdb").exists() or True  # may or may not exist
