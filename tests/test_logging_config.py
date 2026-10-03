"""Tests for src/utils/logging_config.py.

These tests prove that:
    1. configure_logging is idempotent (no duplicate handlers).
    2. The root logger level is set correctly.
    3. Log records do not leak exceptions when no context is supplied.
    4. Third-party noisy loggers are quieted.
"""

from __future__ import annotations

import logging

from src.utils.logging_config import configure_logging, get_logger


def test_configure_logging_is_idempotent() -> None:
    configure_logging(level="INFO", to_file=False)
    n1 = len(logging.getLogger().handlers)
    configure_logging(level="INFO", to_file=False)
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2 == 1  # exactly one console handler


def test_root_level_applied() -> None:
    configure_logging(level="DEBUG", to_file=False)
    assert logging.getLogger().level == logging.DEBUG
    configure_logging(level="INFO", to_file=False)


def test_get_logger_returns_named_logger() -> None:
    log = get_logger("my.module")
    assert log.name == "my.module"


def test_logging_does_not_crash_without_context(caplog) -> None:
    caplog.set_level(logging.INFO)
    log = get_logger("test.module")
    log.info("hello")  # must not raise even though formatter references context
    assert "hello" in caplog.text


def test_noisy_third_party_logger_silenced() -> None:
    configure_logging(level="DEBUG", to_file=False)
    assert logging.getLogger("urllib3").level == logging.WARNING
    configure_logging(level="INFO", to_file=False)
