"""Shopify CSV ingestion.

Responsibility:
    - Read a Shopify CSV file.
    - Apply canonical header mapping.
    - Run row-level structural validation.
    - Return a ValidationResult whose accepted DataFrame has canonical column
      names but untyped values (dates and money are still strings).

What this module explicitly does NOT do:
    - Parse dates (Phase 4).
    - Parse money (Phase 4).
    - Classify financial statuses (Phase 4).
    - Write to DuckDB (Phase 5).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.exceptions import SchemaError
from src.utils.logging_config import get_logger
from src.validation.header_mapper import map_headers
from src.validation.schemas import SHOPIFY_SPECS
from src.validation.validators import (
    DQReport,
    ValidationResult,
    validate_required_values,
    validate_unique_order_ids,
)

log = get_logger(__name__)


def read_shopify_csv(path: Path) -> pd.DataFrame:
    """Read a Shopify CSV into a raw DataFrame. All columns as strings.

    Reads everything as `string` dtype to preserve original representations
    (e.g., "1,250.50", "$150.00") for the cleaning phase. No type coercion
    happens here.
    """
    if not path.exists():
        raise SchemaError("Shopify CSV not found", path=str(path))
    if path.stat().st_size == 0:
        raise SchemaError("Shopify CSV is empty", path=str(path))

    try:
        df = pd.read_csv(
            path,
            dtype="string",
            keep_default_na=False,  # preserve empty strings; we decide what's null
            na_values=[""],
        )
    except pd.errors.EmptyDataError as exc:
        raise SchemaError("Shopify CSV contains no data rows", path=str(path)) from exc
    except pd.errors.ParserError as exc:
        raise SchemaError(
            "Shopify CSV could not be parsed", path=str(path), error=str(exc)
        ) from exc

    log.info(
        "Read Shopify CSV: %d rows, %d columns",
        len(df),
        len(df.columns),
        extra={"context": {"path": str(path), "rows": len(df), "cols": len(df.columns)}},
    )
    return df


def ingest_shopify(
    path: Path,
    *,
    rejection_threshold: float = 1.0,  # 1.0 = never raise; caller decides
) -> tuple[ValidationResult, DQReport]:
    """Full ingestion pipeline for a Shopify CSV.

    Returns:
        (result, report): where result.accepted has canonical column names
        and unvalidated values, and report describes the run.

    Raises:
        SchemaError: if the file is missing, empty, or the schema is wrong.
    """
    raw = read_shopify_csv(path)

    # Step 1: canonical header mapping. Fatal on missing required columns.
    mapped, mapping_report = map_headers(raw, SHOPIFY_SPECS)

    if mapping_report.unexpected:
        log.warning(
            "Unexpected Shopify columns will be ignored by transforms",
            extra={"context": {"unexpected": mapping_report.unexpected}},
        )
    if mapping_report.renamed:
        log.info(
            "Renamed Shopify columns to canonical names",
            extra={"context": {"renamed": mapping_report.renamed}},
        )

    # Step 2: row-level required-value validation.
    required = [spec.canonical for spec in SHOPIFY_SPECS if spec.required]
    result = validate_required_values(mapped, required_fields=required, source="shopify")

    # Step 3: deduplicate on order_id.
    result = validate_unique_order_ids(
        result.accepted,
        id_field="order_id",
        source="shopify",
        report=result.report,
    )

    # Note: `rejection_threshold` here is 1.0 by default so that the ingestion
    # layer doesn't make a policy decision. The pipeline orchestrator (Phase 7)
    # calls `check_rejection_threshold` with the value from settings.
    return result, result.report
