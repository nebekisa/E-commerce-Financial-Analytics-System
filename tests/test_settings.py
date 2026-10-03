"""Tests for config/settings.py.

These tests prove that:
    1. Defaults load and validate.
    2. Invalid timezones are rejected.
    3. FX rate coverage is enforced.
    4. ROAS thresholds are ordered correctly.
    5. `fx_rate()` handles same-currency and unknown-currency cases.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from config.settings import Settings
from pydantic import ValidationError


def test_defaults_load() -> None:
    s = Settings()
    assert s.reporting_currency == "ETB"
    assert s.meta_source_currency == "USD"
    assert s.reporting_timezone == "Africa/Addis_Ababa"
    assert s.usd_to_reporting_fx_rate == Decimal("130.0")
    assert s.cogs_percentage == Decimal("0.40")


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(reporting_timezone="Mars/Olympus_Mons")
    assert "Unknown IANA timezone" in str(exc_info.value)


def test_lowercase_currency_is_uppercased() -> None:
    s = Settings(reporting_currency="etb")
    assert s.reporting_currency == "ETB"


def test_non_alphabetic_currency_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(reporting_currency="E7B")


def test_roas_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(roas_green_threshold=Decimal("1.5"), roas_amber_threshold=Decimal("3.0"))
    assert "amber_threshold must be strictly less" in str(exc_info.value)


def test_fx_rate_same_currency_returns_one() -> None:
    s = Settings(reporting_currency="ETB", etb_to_reporting_fx_rate=Decimal("1.0"))
    assert s.fx_rate("ETB") == Decimal("1.0")


def test_fx_rate_usd_to_etb() -> None:
    s = Settings(reporting_currency="ETB", usd_to_reporting_fx_rate=Decimal("135.5"))
    assert s.fx_rate("USD") == Decimal("135.5")


def test_fx_rate_unknown_currency_raises() -> None:
    s = Settings()
    with pytest.raises(ValueError, match="No FX rate configured for GBP"):
        s.fx_rate("GBP")


def test_negative_fx_rate_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(usd_to_reporting_fx_rate=Decimal("-1"))


def test_cogs_percentage_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(cogs_percentage=Decimal("1.5"))


def test_ensure_directories_creates_paths(tmp_path: Path) -> None:
    s = Settings(
        database_path=tmp_path / "nested" / "analytics.duckdb",
        raw_data_dir=tmp_path / "raw",
        log_dir=tmp_path / "logs",
    )
    s.ensure_directories()
    assert (tmp_path / "nested").is_dir()
    assert (tmp_path / "raw").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPORTING_CURRENCY", "USD")
    monkeypatch.setenv("USD_TO_REPORTING_FX_RATE", "1.0")
    s = Settings()
    assert s.reporting_currency == "USD"
    assert s.fx_rate("USD") == Decimal("1.0")
