"""Tests for src/fx/converter.py."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest
from config.settings import Settings
from src.exceptions import CurrencyError
from src.fx.converter import convert_money_series


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        reporting_currency="ETB",
        usd_to_reporting_fx_rate=Decimal("130.0"),
        etb_to_reporting_fx_rate=Decimal("1.0"),
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_same_currency_returns_identity() -> None:
    amounts = pd.Series([100.0, 200.0], dtype="Float64")
    result = convert_money_series(amounts, source_currency="ETB", settings=_settings())
    assert list(result) == [100.0, 200.0]


def test_usd_to_etb_at_configured_rate() -> None:
    amounts = pd.Series([1.0, 2.0, 10.0], dtype="Float64")
    result = convert_money_series(amounts, source_currency="USD", settings=_settings())
    assert list(result) == [130.0, 260.0, 1300.0]


def test_zero_passes_through() -> None:
    amounts = pd.Series([0.0], dtype="Float64")
    result = convert_money_series(amounts, source_currency="USD", settings=_settings())
    assert result.iloc[0] == 0.0


def test_na_passes_through() -> None:
    amounts = pd.Series([pd.NA, 1.0], dtype="Float64")
    result = convert_money_series(amounts, source_currency="USD", settings=_settings())
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 130.0


def test_unknown_currency_raises() -> None:
    amounts = pd.Series([1.0], dtype="Float64")
    with pytest.raises(CurrencyError) as exc_info:
        convert_money_series(amounts, source_currency="GBP", settings=_settings())
    assert "GBP" in str(exc_info.value)
    assert exc_info.value.context["source_currency"] == "GBP"


def test_case_insensitive_currency_code() -> None:
    amounts = pd.Series([1.0], dtype="Float64")
    result = convert_money_series(amounts, source_currency="usd", settings=_settings())
    assert result.iloc[0] == 130.0


def test_empty_series_returns_empty() -> None:
    amounts = pd.Series([], dtype="Float64")
    result = convert_money_series(amounts, source_currency="USD", settings=_settings())
    assert len(result) == 0


def test_different_rate_changes_result() -> None:
    amounts = pd.Series([1.0], dtype="Float64")
    s1 = _settings(usd_to_reporting_fx_rate=Decimal("130.0"))
    s2 = _settings(usd_to_reporting_fx_rate=Decimal("150.0"))
    assert convert_money_series(amounts, source_currency="USD", settings=s1).iloc[0] == 130.0
    assert convert_money_series(amounts, source_currency="USD", settings=s2).iloc[0] == 150.0


def test_rejects_non_series() -> None:
    with pytest.raises(TypeError):
        convert_money_series([1.0], source_currency="USD", settings=_settings())  # type: ignore[arg-type]
