"""Currency conversion.

All monetary values entering the financial model pass through this module.
It applies the configured FX rate and returns values in the reporting
currency.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from config.settings import Settings
from src.exceptions import CurrencyError
from src.utils.logging_config import get_logger

log = get_logger(__name__)


def convert_money_series(
    amounts: pd.Series[Any],
    *,
    source_currency: str,
    settings: Settings,
) -> pd.Series[Any]:
    """Convert a money Series from source_currency to settings.reporting_currency.

    Args:
        amounts: Float64 Series of monetary values in source_currency.
        source_currency: ISO 4217 code of the source (e.g., "USD").
        settings: Configuration with reporting currency and FX rates.

    Returns:
        Float64 Series of the same length, in reporting currency.

    Raises:
        CurrencyError: if source_currency has no configured rate and does not
            equal the reporting currency.
    """
    if not isinstance(amounts, pd.Series):
        raise TypeError(f"convert_money_series expects pd.Series, got {type(amounts)!r}")

    source = source_currency.upper()
    reporting = settings.reporting_currency.upper()

    if source == reporting:
        return amounts.astype("Float64")

    try:
        rate_decimal = settings.fx_rate(source)
    except ValueError as exc:
        raise CurrencyError(
            f"Cannot convert {source} to {reporting}",
            source_currency=source,
            reporting_currency=reporting,
        ) from exc

    rate_float = float(rate_decimal)

    log.debug(
        "Converting %d rows from %s to %s at rate %s",
        len(amounts),
        source,
        reporting,
        rate_decimal,
        extra={
            "context": {
                "source_currency": source,
                "reporting_currency": reporting,
                "rate": str(rate_decimal),
                "rows": len(amounts),
            }
        },
    )

    return (amounts * rate_float).astype("Float64")
