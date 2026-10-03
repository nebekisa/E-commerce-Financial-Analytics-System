"""Shared pytest fixtures.

Fixtures here are session-scoped where they are expensive (like logging
configuration) and function-scoped where isolation matters.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from config.settings import Settings
from src.utils.logging_config import configure_logging


@pytest.fixture(scope="session", autouse=True)
def _configure_test_logging() -> None:
    """Configure logging once per test session, console-only, WARNING level.

    Tests should be quiet by default. If a test needs to assert on log output,
    it should attach its own handler via caplog.
    """
    configure_logging(level="WARNING", to_file=False)


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """A Settings instance pointed at a temporary directory.

    Use this whenever a test needs a Settings object that doesn't touch the
    real data/ or logs/ directories.
    """
    return Settings(
        database_path=tmp_path / "analytics.duckdb",
        raw_data_dir=tmp_path / "raw",
        log_dir=tmp_path / "logs",
    )


@pytest.fixture
def caplog_at(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    """Set the root logger level during a test so caplog captures records."""
    caplog.set_level(logging.DEBUG)
    return caplog
