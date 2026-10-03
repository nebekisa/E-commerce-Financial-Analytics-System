"""Tests for src/cli.py.

These tests exercise argument parsing, settings overrides, exit codes, and
the summary printer. They do not run the full pipeline — that's covered by
tests/test_pipeline.py.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from src.cli import _build_parser, _print_summary, _settings_from_args, main
from src.pipeline import PipelineResult
from src.validation.validators import DQReport

FIXTURES = Path(__file__).parent / "fixtures"
SQL_DIR = Path(__file__).parent.parent / "sql"


# ---------------------------------------------------------------------- #
# Argument parsing                                                        #
# ---------------------------------------------------------------------- #


def test_parser_requires_shopify_and_meta() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_accepts_required_args() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--shopify", "a.csv", "--meta", "b.csv"])
    assert args.shopify == Path("a.csv")
    assert args.meta == Path("b.csv")
    assert args.database is None
    assert args.sql_dir == Path("sql")


def test_parser_accepts_all_options() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--shopify",
            "a.csv",
            "--meta",
            "b.csv",
            "--database",
            "custom.duckdb",
            "--sql-dir",
            "custom_sql",
            "--reporting-currency",
            "USD",
            "--fx-rate",
            "1.0",
            "--log-level",
            "DEBUG",
        ]
    )
    assert args.database == Path("custom.duckdb")
    assert args.sql_dir == Path("custom_sql")
    assert args.reporting_currency == "USD"
    assert args.fx_rate == "1.0"
    assert args.log_level == "DEBUG"


def test_parser_rejects_invalid_log_level() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--shopify",
                "a.csv",
                "--meta",
                "b.csv",
                "--log-level",
                "VERBOSE",
            ]
        )


# ---------------------------------------------------------------------- #
# Settings construction                                                   #
# ---------------------------------------------------------------------- #


def test_settings_from_args_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--shopify", "a.csv", "--meta", "b.csv"])
    s = _settings_from_args(args)
    # Defaults come from the environment-driven Settings.
    assert s.reporting_currency == "ETB"


def test_settings_from_args_overrides() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--shopify",
            "a.csv",
            "--meta",
            "b.csv",
            "--reporting-currency",
            "USD",
            "--fx-rate",
            "1.0",
            "--database",
            "custom.duckdb",
        ]
    )
    s = _settings_from_args(args)
    assert s.reporting_currency == "USD"
    assert s.usd_to_reporting_fx_rate == Decimal("1.0")
    assert s.database_path == Path("custom.duckdb")


# ---------------------------------------------------------------------- #
# Summary printer                                                         #
# ---------------------------------------------------------------------- #


def _sample_result() -> PipelineResult:
    return PipelineResult(
        shopify_report=DQReport(
            source="shopify",
            rows_received=8,
            rows_accepted=6,
            rows_rejected=2,
            rejection_reasons={"excluded_status": 2},
        ),
        meta_report=DQReport(
            source="meta_ads",
            rows_received=5,
            rows_accepted=5,
            rows_rejected=0,
            rejection_reasons={},
        ),
        database_path=Path("data/processed/analytics.duckdb"),
        sql_dir=Path("sql"),
        dates_min="2026-09-01",
        dates_max="2026-09-05",
        total_net_revenue=3580.0,
        total_ad_spend=19500.0,
        total_contribution_margin=-17440.0,
        currency="ETB",
    )


def test_print_summary_outputs_key_facts(capsys) -> None:
    _print_summary(_sample_result())
    captured = capsys.readouterr().out
    assert "2026-09-01 .. 2026-09-05" in captured
    assert "3,580.00 ETB" in captured
    assert "19,500.00 ETB" in captured
    assert "-17,440.00 ETB" in captured
    assert "excluded_status: 2" in captured
    assert "daily_financial_model" in captured


# ---------------------------------------------------------------------- #
# End-to-end CLI runs                                                     #
# ---------------------------------------------------------------------- #


def test_main_returns_zero_on_success(tmp_path: Path) -> None:
    code = main(
        [
            "--shopify",
            str(FIXTURES / "golden_shopify.csv"),
            "--meta",
            str(FIXTURES / "golden_meta.csv"),
            "--database",
            str(tmp_path / "cli.duckdb"),
            "--sql-dir",
            str(SQL_DIR),
            "--log-level",
            "ERROR",  # keep test output quiet
        ]
    )
    assert code == 0


def test_main_returns_nonzero_on_missing_file(tmp_path: Path) -> None:
    code = main(
        [
            "--shopify",
            str(tmp_path / "nope.csv"),
            "--meta",
            str(FIXTURES / "golden_meta.csv"),
            "--database",
            str(tmp_path / "cli.duckdb"),
            "--sql-dir",
            str(SQL_DIR),
            "--log-level",
            "ERROR",
        ]
    )
    assert code == 2  # _EXIT_SCHEMA


def test_main_returns_nonzero_on_bad_fx_rate(tmp_path: Path) -> None:
    code = main(
        [
            "--shopify",
            str(FIXTURES / "golden_shopify.csv"),
            "--meta",
            str(FIXTURES / "golden_meta.csv"),
            "--database",
            str(tmp_path / "cli.duckdb"),
            "--sql-dir",
            str(SQL_DIR),
            "--fx-rate",
            "-1",  # invalid: must be > 0
            "--log-level",
            "ERROR",
        ]
    )
    assert code == 7  # _EXIT_CONFIGURATION
