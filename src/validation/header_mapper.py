"""Header normalization and canonical column mapping.

Given a raw DataFrame (as read from a CSV by pandas), produce a new DataFrame
whose columns are the canonical internal field names, and a mapping report
describing what was renamed, what was unexpected, and what was missing.

This module does NOT:
    - parse values (dates, money, statuses)
    - validate business rules
    - write to disk

It is purely a column-name translation layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from src.exceptions import SchemaError

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_header(raw: str) -> str:
    """Normalize a raw header to a canonical, comparable form.

    Rules:
        - lowercase
        - strip whitespace
        - collapse runs of non-alphanumeric characters to a single '_'
        - strip leading/trailing '_'

    Examples:
        >>> normalize_header("Created At ")
        'created_at'
        >>> normalize_header("Gross Amount ($)")
        'gross_amount'
        >>> normalize_header("  ORDER--ID  ")
        'order_id'
    """
    s = raw.strip().lower()
    s = _NON_ALNUM.sub("_", s)
    return s.strip("_")


@dataclass(frozen=True)
class ColumnSpec:
    """Specification for one canonical field."""

    canonical: str
    aliases: frozenset[str]
    required: bool

    def matches(self, normalized_header: str) -> bool:
        return normalized_header == self.canonical or normalized_header in self.aliases


@dataclass
class MappingReport:
    """Result of mapping raw headers to canonical fields."""

    renamed: dict[str, str] = field(default_factory=dict)  # raw -> canonical
    missing_required: list[str] = field(default_factory=list)  # canonical names
    unexpected: list[str] = field(default_factory=list)  # raw names
    duplicates: list[str] = field(default_factory=list)  # raw names (post-pandas)


def map_headers(
    df: pd.DataFrame,
    specs: list[ColumnSpec],
) -> tuple[pd.DataFrame, MappingReport]:
    """Rename DataFrame columns to canonical names based on the given specs.

    Raises:
        SchemaError: if a required canonical field is missing, or if two raw
            headers map to the same canonical field.
    """
    report = MappingReport()

    # Detect pandas' duplicate-suffix pattern (col, col.1, col.2, ...).
    # pandas adds these silently; we want to know.
    dup_pattern = re.compile(r"^(?P<base>.+)\.\d+$")

    for raw in df.columns:
        m = dup_pattern.match(str(raw))
        if m:
            base = m.group("base")
            if base in df.columns:
                report.duplicates.append(str(raw))

    if report.duplicates:
        raise SchemaError(
            "Duplicate column names detected in input",
            duplicates=report.duplicates,
        )

    # Build the mapping: normalized header -> raw header.
    normalized_to_raw: dict[str, str] = {}
    for raw in df.columns:
        norm = normalize_header(str(raw))
        if norm in normalized_to_raw:
            raise SchemaError(
                "Two raw headers normalize to the same name",
                first=normalized_to_raw[norm],
                second=str(raw),
                normalized=norm,
            )
        normalized_to_raw[norm] = str(raw)

    rename_map: dict[str, str] = {}
    matched_canonicals: set[str] = set()

    for spec in specs:
        matched_raw: str | None = None
        for norm, raw in normalized_to_raw.items():
            if spec.matches(norm):
                matched_raw = raw
                break

        if matched_raw is None:
            if spec.required:
                report.missing_required.append(spec.canonical)
            continue

        matched_canonicals.add(spec.canonical)
        if matched_raw != spec.canonical:
            rename_map[matched_raw] = spec.canonical
            report.renamed[matched_raw] = spec.canonical

    if report.missing_required:
        raise SchemaError(
            "Missing required columns",
            missing=report.missing_required,
            provided=list(df.columns),
        )

    # Anything not matched by a spec is unexpected. We keep it.
    for raw in df.columns:
        if str(raw) in rename_map:
            continue
        norm = normalize_header(str(raw))
        matched = any(spec.matches(norm) for spec in specs)
        if not matched:
            report.unexpected.append(str(raw))

    out = df.rename(columns=rename_map)
    return out, report
