"""Typed exception hierarchy for the analytics pipeline.

Every error raised inside the pipeline is a subclass of PipelineError. This
gives the CLI a single base class to map to exit codes and gives Streamlit a
single base class to map to user-facing messages, while preserving enough
specificity for targeted handling where needed.

Rule: never raise bare `Exception`. Never catch bare `Exception` unless you
re-raise or convert to one of these types.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base class for all pipeline errors.

    Attributes:
        message: Human-readable explanation.
        context: Optional dict of structured fields for logging.
    """

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def __str__(self) -> str:
        if not self.context:
            return self.message
        ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{self.message} ({ctx})"


class ConfigurationError(PipelineError):
    """Raised when configuration is missing, invalid, or inconsistent."""


class SchemaError(PipelineError):
    """Raised when an input file's schema is fatally wrong.

    Examples: missing required column, unreadable file, empty file.
    These are FATAL — the pipeline stops.
    """


class DataQualityError(PipelineError):
    """Raised when row-level data quality crosses a fatal threshold.

    Row-level issues are typically RECOVERABLE (reject the row, continue).
    This exception is for cases where the *aggregate* quality is so poor that
    continuing would produce misleading results.
    """


class TransformationError(PipelineError):
    """Raised when a transformation step cannot proceed.

    Distinct from DataQualityError: this is a bug or an unexpected data shape,
    not a row-level data issue.
    """


class CurrencyError(PipelineError):
    """Raised when a currency conversion is impossible or ambiguous.

    Examples: missing FX rate, unknown ISO code, mixing currencies without
    a defined conversion path.
    """


class DatabaseError(PipelineError):
    """Raised when DuckDB operations fail.

    Examples: file lock, corrupt database, SQL syntax error in our own SQL.
    """
