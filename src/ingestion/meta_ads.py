"""Meta Ads CSV ingestion.

Responsibility:
    - Read a Meta Ads Manager CSV export.
    - Apply canonical header mapping (via the shared header_mapper).
    - Run row-level structural validation.
    - Return a ValidationResult whose accepted DataFrame has canonical column
      names but untyped values (dates, money, and counts are still strings).

What this module explicitly does NOT do:
    - Parse dates (Phase 4).
    - Decide whether rows are daily or multi-day intervals (Phase 4).
    - Parse money (Phase 4).
    - Aggregate by date (Phase 5).
    - Write to DuckDB (Phase 5).

Design notes:
    - Meta's optional columns (campaign_name, impressions, link_clicks) are
      allowed to be absent. When absent, they are simply not in the returned
      DataFrame; downstream code must handle their absence via .get() or a
      coalesce pattern in SQL.
    - Unlike Shopify, we do NOT deduplicate on a key. Meta does not export a
      stable row identifier, and campaign names are not guaranteed unique
      across dates. Duplicate detection happens later, at the grain of
      (calendar_date, campaign_name), if needed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.exceptions import SchemaError
from src.utils.logging_config import get_logger
from src.validation.header_mapper import map_headers
from src.validation.schemas import META_SPECS
from src.validation.validators import (
    DQReport,
    ValidationResult,
    validate_required_values,
)

log = get_logger(__name__)


def read_meta_csv(path: Path) -> pd.DataFrame:
    """Read a Meta Ads CSV into a raw DataFrame. All columns as strings.

    Same contract as read_shopify_csv: no type coercion, empty strings become
    NaN, other NA-looking strings (e.g., "N/A", "null") are preserved.
    """
    if not path.exists():
        raise SchemaError("Meta Ads CSV not found", path=str(path))
    if path.stat().st_size == 0:
        raise SchemaError("Meta Ads CSV is empty", path=str(path))

    try:
        df = pd.read_csv(
            path,
            dtype="string",
            keep_default_na=False,
            na_values=[""],
        )
    except pd.errors.EmptyDataError as exc:
        raise SchemaError("Meta Ads CSV contains no data rows", path=str(path)) from exc
    except pd.errors.ParserError as exc:
        raise SchemaError(
            "Meta Ads CSV could not be parsed", path=str(path), error=str(exc)
        ) from exc

    log.info(
        "Read Meta Ads CSV: %d rows, %d columns",
        len(df),
        len(df.columns),
        extra={"context": {"path": str(path), "rows": len(df), "cols": len(df.columns)}},
    )
    return df


def ingest_meta_ads(path: Path) -> tuple[ValidationResult, DQReport]:
    """Full ingestion pipeline for a Meta Ads CSV.

    Returns:
        (result, report): where result.accepted has canonical column names
        and unvalidated values, and report describes the run.

    Raises:
        SchemaError: if the file is missing, empty, or the schema is wrong.
    """
    raw = read_meta_csv(path)

    # Step 1: canonical header mapping. Fatal on missing required columns.
    mapped, mapping_report = map_headers(raw, META_SPECS)

    if mapping_report.unexpected:
        log.warning(
            "Unexpected Meta Ads columns will be ignored by transforms",
            extra={"context": {"unexpected": mapping_report.unexpected}},
        )
    if mapping_report.renamed:
        log.info(
            "Renamed Meta Ads columns to canonical names",
            extra={"context": {"renamed": mapping_report.renamed}},
        )

    # Step 2: row-level required-value validation.
    # Only reporting_start, reporting_end, and spend_amount are required.
    required = [spec.canonical for spec in META_SPECS if spec.required]
    result = validate_required_values(mapped, required_fields=required, source="meta_ads")

    # Step 3: no deduplication for Meta (see module docstring).

    return result, result.report
