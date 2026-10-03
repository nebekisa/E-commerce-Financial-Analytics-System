"""Logging configuration for the pipeline.

Centralized configuration so that CLI, Streamlit, and tests all produce
consistent, structured output. Logging is configured ONCE at the application
boundary (CLI entrypoint, Streamlit entrypoint, test session start) and never
inside library modules.

Design choices:
    - One formatter for console (human-readable), one for file (structured).
    - File logs rotate at 5 MB, keep 5 backups.
    - No customer identifiers ever enter log messages; callers must pass only
      aggregate counts, IDs of internal entities (order_id is borderline and
      is logged only at DEBUG), and structured context dicts.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_CONFIGURED = False

_CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


class _ContextFilter(logging.Filter):
    """Ensure every record has a `context` attribute.

    Pipeline exceptions carry a `context` dict. This filter makes that dict
    available to formatters without forcing every log call to pass `extra`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "context"):
            record.context = {}
        return True


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,
    log_filename: str = "pipeline.log",
    to_console: bool = True,
    to_file: bool | None = None,
) -> None:
    """Configure the root logger. Idempotent — safe to call multiple times.

    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        log_dir: Directory for the log file. If None and to_file is True,
            defaults to `logs/` in the CWD.
        log_filename: Name of the rotating log file.
        to_console: Whether to emit logs to stderr.
        to_file: Whether to emit logs to a rotating file. If None, defaults
            to True when log_dir is provided, False otherwise.
    """
    global _CONFIGURED

    root = logging.getLogger()
    root.setLevel(level.upper())

    # Idempotency: clear existing handlers so repeated calls don't duplicate.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter_console = logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT)
    formatter_file = logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT)
    context_filter = _ContextFilter()

    if to_console:
        console = logging.StreamHandler(stream=sys.stderr)
        console.setFormatter(formatter_console)
        console.addFilter(context_filter)
        root.addHandler(console)

    if to_file is None:
        to_file = log_dir is not None

    if to_file:
        target_dir = log_dir or Path("logs")
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=target_dir / log_filename,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter_file)
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)

    # Silence chatty third-party loggers that would otherwise pollute output.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name.

    If logging has not been configured yet, applies a safe default (INFO to
    console only) so that library imports don't crash in isolation.
    """
    if not _CONFIGURED:
        configure_logging(level="INFO", to_file=False)
    return logging.getLogger(name)
