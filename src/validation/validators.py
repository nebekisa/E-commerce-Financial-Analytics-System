"""Row-level validation for ingested DataFrames.

Schema validation (column presence, header mapping) happens in
`header_mapper.map_headers`. This module handles per-row checks that are
recoverable: reject the row, log it, keep going.

The output of validation is a ValidationResult, which downstream phases
consume. It contains:
    - accepted: DataFrame with valid rows, original index reset
    - rejected: DataFrame with rejected rows + a `rejection_reason` column
    - report: DQReport with aggregate counts
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.exceptions import DataQualityError
from src.utils.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class DQReport:
    """Aggregate data-quality statistics for one source ingestion."""

    source: str
    rows_received: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def rejection_rate(self) -> float:
        if self.rows_received == 0:
            return 0.0
        return self.rows_rejected / self.rows_received

    def add_rejection(self, reason: str, count: int = 1) -> None:
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + count


@dataclass
class ValidationResult:
    """Result of row-level validation."""

    accepted: pd.DataFrame
    rejected: pd.DataFrame
    report: DQReport


def validate_required_values(
    df: pd.DataFrame,
    *,
    required_fields: list[str],
    source: str,
) -> ValidationResult:
    """Check that required fields are non-null and non-empty per row.

    Rows with missing required values are moved to the rejected DataFrame
    with a `rejection_reason` column. Accepted rows preserve their original
    index so that downstream stages can trace them back to source rows.
    """
    report = DQReport(source=source, rows_received=len(df))

    if df.empty:
        log.warning(
            "Empty DataFrame passed to validate_required_values",
            extra={"context": {"source": source}},
        )
        return ValidationResult(
            accepted=df.copy(),
            rejected=df.iloc[0:0].assign(rejection_reason=pd.Series(dtype="string")),
            report=report,
        )

    # Empty-row check: rows where every value is null/empty.
    empty_mask = df.isna().all(axis=1)
    # Missing-required check: any required field is null or whitespace-only.
    required_present = pd.Series(True, index=df.index)
    for col in required_fields:
        col_values = df[col]
        # Treat NaN, empty string, and whitespace-only strings as missing.
        is_missing = col_values.isna() | (col_values.astype("string").str.strip() == "")
        required_present &= ~is_missing

    valid_mask = required_present & ~empty_mask

    rejected = df.loc[~valid_mask].copy()
    accepted = df.loc[valid_mask].copy()

    # Assign rejection reasons in priority order.
    if not rejected.empty:
        reasons = pd.Series("missing_required_value", index=rejected.index, dtype="string")
        reasons[empty_mask.loc[rejected.index]] = "empty_row"
        rejected["rejection_reason"] = reasons
        counts = rejected["rejection_reason"].value_counts().to_dict()
        for reason, count in counts.items():
            report.add_rejection(str(reason), int(count))

    report.rows_accepted = len(accepted)
    report.rows_rejected = len(rejected)

    log.info(
        "Validated %s: %d accepted, %d rejected",
        source,
        report.rows_accepted,
        report.rows_rejected,
        extra={
            "context": {
                "source": source,
                "accepted": report.rows_accepted,
                "rejected": report.rows_rejected,
                "reasons": report.rejection_reasons,
            }
        },
    )

    return ValidationResult(accepted=accepted, rejected=rejected, report=report)


def validate_unique_order_ids(
    df: pd.DataFrame,
    *,
    id_field: str,
    source: str,
    report: DQReport,
) -> ValidationResult:
    """Enforce uniqueness on the given ID field.

    Keeps the first occurrence of each ID; rejects subsequent duplicates.
    Mutates and returns a new ValidationResult; updates `report` in place.
    """
    if df.empty:
        return ValidationResult(
            accepted=df.copy(),
            rejected=df.iloc[0:0].assign(rejection_reason=pd.Series(dtype="string")),
            report=report,
        )

    is_dup = df[id_field].duplicated(keep="first")
    accepted = df.loc[~is_dup].copy()
    rejected = df.loc[is_dup].copy()
    if not rejected.empty:
        rejected["rejection_reason"] = "duplicate_order_id"
        report.add_rejection("duplicate_order_id", len(rejected))

    report.rows_accepted = len(accepted)
    report.rows_rejected += len(rejected)

    log.info(
        "Deduplicated %s on %s: %d duplicates removed",
        source,
        id_field,
        len(rejected),
        extra={"context": {"source": source, "field": id_field, "duplicates": len(rejected)}},
    )

    return ValidationResult(accepted=accepted, rejected=rejected, report=report)


def check_rejection_threshold(
    report: DQReport,
    *,
    threshold: float,
) -> None:
    """Raise DataQualityError if the rejection rate exceeds the threshold."""
    if report.rejection_rate > threshold:
        raise DataQualityError(
            f"Rejection rate {report.rejection_rate:.1%} exceeds threshold {threshold:.1%}",
            source=report.source,
            rows_received=report.rows_received,
            rows_rejected=report.rows_rejected,
            threshold=threshold,
        )
