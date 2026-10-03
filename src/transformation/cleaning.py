"""Shared value-cleaning primitives.

Money parsing, date parsing, and text normalization are used by both Shopify
and Meta transforms. They live here, not in the source-specific modules, so:
    - behavior is identical across sources
    - bugs are fixed in one place
    - tests are written once

Design principles:
    1. Parsers are vectorized. No .apply(), no Python loops, no per-row work.
    2. Parsers return NA for unparseable input. Never 0, never "".
    3. Parsers do not raise on bad input. The caller decides whether NA is a
       rejection, a warning, or a legitimate null.
    4. Parsers do not extract currency. The caller knows the column's currency
       from config or from a dedicated currency column. See fx/converter.py.

Type-checking note:
    pandas-stubs is stricter than the pandas runtime in a few places. Where
    the runtime accepts a compiled regex pattern but the stub only declares
    `str`, we keep the compiled pattern (because lookbehind is required) and
    silence the specific error with a comment. These ignores are intentional
    and each is explained at the point of use.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from src.utils.logging_config import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------- #
# Money parsing                                                           #
# ---------------------------------------------------------------------- #

# Strip patterns, in order. Order matters:
#   1. Currency codes (whole-word 3-letter uppercase) -> removed
#   2. Currency symbols -> removed
#   3. Thousands separators (comma/space between digit groups) -> removed
#   4. Whitespace -> stripped
#
# The thousands-separator pattern uses lookbehind/lookahead, which requires
# a compiled re.Pattern. pandas' `.str.replace(regex=True)` accepts it at
# runtime, but pandas-stubs only declares `str`. We ignore the stub error.
_THOUSANDS_SEPARATORS = re.compile(r"(?<=\d)[,\s](?=\d{3}(?!\d))")
_CURRENCY_SYMBOLS = re.compile(r"[$€£¥₹₽₺₴₦₱₲₵₡₭₮₸]")
_CURRENCY_CODES = re.compile(r"\b[A-Z]{3}\b")
_PARENTHESES_NEGATIVE = re.compile(r"^\((.*)\)$")


def parse_money_series(s: pd.Series[Any]) -> pd.Series[Any]:
    """Parse a Series of money-like strings into Float64.

    Examples:
        "150.00"        -> 150.0
        "1,250.50"      -> 1250.5
        "$150.00"       -> 150.0
        "ETB 150.00"    -> 150.0
        "$1,250.00 ETB" -> 1250.0
        "(150.00)"      -> -150.0   (accounting negative)
        "" / None / NA  -> pd.NA
        "abc"           -> pd.NA
        "1,25"          -> pd.NA    (ambiguous, rejected)

    Returns Float64 (nullable float) so that NA is representable distinctly
    from 0.0.
    """
    if not isinstance(s, pd.Series):
        raise TypeError(f"parse_money_series expects pd.Series, got {type(s)!r}")

    if len(s) == 0:
        return pd.Series([], dtype="Float64")

    working = s.astype("string")

    paren_negative = working.str.match(_PARENTHESES_NEGATIVE, na=False)  # type: ignore[arg-type]
    working = working.str.replace(_PARENTHESES_NEGATIVE, r"\1", regex=True)  # type: ignore[arg-type]
    working = working.str.replace(_CURRENCY_CODES, "", regex=True)  # type: ignore[arg-type]
    working = working.str.replace(_CURRENCY_SYMBOLS, "", regex=True)  # type: ignore[arg-type]
    working = working.str.replace(_THOUSANDS_SEPARATORS, "", regex=True)  # type: ignore[arg-type]
    working = working.str.strip()
    working = working.replace("", pd.NA)

    parsed = pd.to_numeric(working, errors="coerce").astype("Float64")
    parsed = parsed.where(~paren_negative, -parsed)
    return parsed


# ---------------------------------------------------------------------- #
# Date parsing                                                            #
# ---------------------------------------------------------------------- #

_TIMESTAMP_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _is_tz_aware(dtype: Any) -> bool:
    """Return True if dtype is a tz-aware datetime dtype.

    Uses isinstance against DatetimeTZDtype rather than the deprecated
    pd.api.types.is_datetime64tz_dtype, which was removed in pandas 2.0.
    """
    return isinstance(dtype, pd.DatetimeTZDtype)


def parse_timestamp_series(s: pd.Series[Any]) -> pd.Series[Any]:
    """Parse a Series of timestamp strings into tz-aware UTC datetimes.

    Returns dtype datetime64[ns, UTC]. Unparseable values are NaT.
    """
    if not isinstance(s, pd.Series):
        raise TypeError(f"parse_timestamp_series expects pd.Series, got {type(s)!r}")

    if len(s) == 0:
        return pd.Series([], dtype="datetime64[ns, UTC]")

    if _is_tz_aware(s.dtype):
        return s.dt.tz_convert("UTC")

    working = s.astype("string")

    utc_suffix = working.str.strip().str.endswith("UTC", na=False)
    working = working.str.replace(r"\s*UTC\s*$", "", regex=True)

    result = pd.Series(pd.NaT, index=working.index, dtype="datetime64[ns, UTC]")

    for fmt in _TIMESTAMP_FORMATS:
        unparsed = result.isna()
        if not unparsed.any():
            break
        subset = working.loc[unparsed].dropna()
        if subset.empty:
            continue
        attempt = pd.to_datetime(subset, format=fmt, errors="coerce", utc=True)
        result.loc[attempt.index] = attempt

    still_na_with_utc = result.isna() & utc_suffix
    if still_na_with_utc.any():
        log.debug(
            "Failed to parse %d timestamps that ended with 'UTC'",
            int(still_na_with_utc.sum()),
        )

    return result


def to_reporting_date(
    timestamps: pd.Series[Any],
    *,
    reporting_timezone: str,
) -> pd.Series[Any]:
    """Convert a UTC timestamp Series to calendar dates in the reporting TZ.

    This is THE function that defines what `calendar_date` means for the
    business. It is a business-semantics function, not a formatting one.

    Example (reporting_timezone="Africa/Addis_Ababa", UTC+3):
        "2026-09-01 22:30 UTC" -> "2026-09-02 01:30 local" -> date(2026, 9, 2)
        "2026-09-01 20:30 UTC" -> "2026-09-01 23:30 local" -> date(2026, 9, 1)
    """
    if not _is_tz_aware(timestamps.dtype):
        raise TypeError(
            f"to_reporting_date expects a tz-aware Series, got dtype "
            f"{timestamps.dtype!r}. Parse to UTC first."
        )
    local = timestamps.dt.tz_convert(reporting_timezone)
    return local.dt.date


def parse_date_series(s: pd.Series[Any]) -> pd.Series[Any]:
    """Parse a Series of date-only strings into Python `date` objects.

    Used for Meta's Reporting Start / Reporting End. These are NOT
    timezone-converted — the caller decides how to attach them to the
    reporting calendar.
    """
    if not isinstance(s, pd.Series):
        raise TypeError(f"parse_date_series expects pd.Series, got {type(s)!r}")

    if len(s) == 0:
        return pd.Series([], dtype="object")

    working = s.astype("string").str.strip()

    parsed = pd.to_datetime(working, format="%Y-%m-%d", errors="coerce")
    still_na = parsed.isna()
    if still_na.any():
        slash_attempt = pd.to_datetime(
            working.loc[still_na],
            format="%Y/%m/%d",
            errors="coerce",
        )
        parsed.loc[slash_attempt.index] = slash_attempt

    return parsed.dt.date


# ---------------------------------------------------------------------- #
# Text normalization                                                      #
# ---------------------------------------------------------------------- #

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_status_series(s: pd.Series[Any]) -> pd.Series[Any]:
    """Normalize financial status strings for comparison."""
    return (
        s.astype("string")
        .str.strip()
        .str.lower()
        .str.replace(r"[\s\-]+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
    )


def normalize_campaign_series(s: pd.Series[Any]) -> pd.Series[Any]:
    """Light normalization for campaign names. Preserves original casing."""
    return (
        s.astype("string")
        .str.strip()
        .str.replace(_WHITESPACE_RUN, " ", regex=True)  # type: ignore[arg-type]
        .replace("", pd.NA)
    )
