"""Central configuration for the financial analytics pipeline.

All runtime configuration is expressed here exactly once. Downstream modules
import the singleton `settings` object; they never read environment variables
directly. This keeps configuration auditable and testable.

Precedence (highest to lowest):
    1. Explicit arguments to `Settings(...)`
    2. Environment variables
    3. Values in a `.env` file (loaded via python-dotenv)
    4. Field defaults below
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Paths                                                              #
    # ------------------------------------------------------------------ #
    database_path: Path = Field(
        default=Path("data/processed/analytics.duckdb"),
        description="Location of the DuckDB file used as the analytical store.",
    )
    raw_data_dir: Path = Field(
        default=Path("data/raw"),
        description="Directory for uploaded/raw CSV files.",
    )
    log_dir: Path = Field(
        default=Path("logs"),
        description="Directory for log files.",
    )

    # ------------------------------------------------------------------ #
    # Timezone & currency                                                #
    # ------------------------------------------------------------------ #
    reporting_timezone: str = Field(
        default="Africa/Addis_Ababa",
        description="IANA timezone used to derive calendar_date from timestamps.",
    )
    reporting_currency: str = Field(
        default="ETB",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code for all reported monetary values.",
    )
    shopify_source_currency: str = Field(
        default="ETB",
        min_length=3,
        max_length=3,
        description="Currency of Shopify revenue columns in the source export.",
    )
    meta_source_currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="Currency of Meta ad spend columns in the source export.",
    )

    # FX rate: how many units of reporting_currency per 1 unit of source.
    # Example: usd_to_reporting_fx_rate=130.0 means 1 USD = 130 ETB.
    usd_to_reporting_fx_rate: Decimal = Field(
        default=Decimal("130.0"),
        gt=0,
        description="FX rate: 1 USD = N reporting currency units.",
    )
    etb_to_reporting_fx_rate: Decimal = Field(
        default=Decimal("1.0"),
        gt=0,
        description="FX rate: 1 ETB = N reporting currency units.",
    )

    # ------------------------------------------------------------------ #
    # Business assumptions                                               #
    # ------------------------------------------------------------------ #
    cogs_percentage: Decimal = Field(
        default=Decimal("0.40"),
        ge=0,
        le=1,
        description="Estimated COGS as a fraction of gross revenue.",
    )
    admin_hours_per_week: Decimal = Field(
        default=Decimal("4.0"),
        ge=0,
        description="Client-reported hours of manual work replaced per week.",
    )

    # Revenue-recognizing financial statuses. Lowercase, underscore-normalized.
    # Revenue-recognizing financial statuses. Lowercase, underscore-normalized.
    # These are the statuses whose orders contribute to recognized revenue.
    # See Phase 4 kickoff decision #3.
    revenue_statuses: frozenset[str] = Field(
        default=frozenset({"paid", "partially_paid", "partially_refunded"}),
        description="Shopify financial_status values that count as recognized revenue.",
    )
    excluded_statuses: frozenset[str] = Field(
        default=frozenset({"pending", "cancelled", "refunded", "voided"}),
        description="Statuses explicitly excluded from recognized revenue.",
    )

    # ROAS colour thresholds (client-defined, not universal standards).
    roas_green_threshold: Decimal = Field(
        default=Decimal("3.0"),
        gt=0,
        description="ROAS at or above this value renders green.",
    )
    roas_amber_threshold: Decimal = Field(
        default=Decimal("1.5"),
        gt=0,
        description="ROAS at or above this value (and below green) renders amber.",
    )

    # Data quality
    dq_rejection_threshold: Decimal = Field(
        default=Decimal("0.05"),
        ge=0,
        le=1,
        description="Rejected-row fraction above which the dashboard warns.",
    )

    # ------------------------------------------------------------------ #
    # Logging                                                            #
    # ------------------------------------------------------------------ #
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Minimum severity for log records.",
    )

    # ------------------------------------------------------------------ #
    # Validators                                                         #
    # ------------------------------------------------------------------ #
    @field_validator("reporting_timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {v!r}") from exc
        return v

    @field_validator("reporting_currency", "shopify_source_currency", "meta_source_currency")
    @classmethod
    def _validate_currency_code(cls, v: str) -> str:
        v_upper = v.upper()
        if not v_upper.isalpha():
            raise ValueError(f"Currency code must be alphabetic, got {v!r}")
        return v_upper

    @model_validator(mode="after")
    def _validate_thresholds(self) -> Settings:
        if self.roas_amber_threshold >= self.roas_green_threshold:
            raise ValueError("roas_amber_threshold must be strictly less than roas_green_threshold")
        return self

    @model_validator(mode="after")
    def _validate_fx_coverage(self) -> Settings:
        # If a source currency equals the reporting currency, its rate must be 1.
        if (
            self.shopify_source_currency == self.reporting_currency
            and self.etb_to_reporting_fx_rate != Decimal("1.0")
            and self.shopify_source_currency == "ETB"
        ):
            raise ValueError("ETB→reporting rate must be 1.0 when reporting currency is ETB")
        if (
            self.meta_source_currency == self.reporting_currency
            and self.meta_source_currency == "USD"
            and self.usd_to_reporting_fx_rate != Decimal("1.0")
        ):
            raise ValueError("USD→reporting rate must be 1.0 when reporting currency is USD")
        return self

    # ------------------------------------------------------------------ #
    # Derived helpers                                                    #
    # ------------------------------------------------------------------ #
    def fx_rate(self, source_currency: str) -> Decimal:
        """Return the configured rate: 1 unit of source = N units reporting.

        Raises:
            ValueError: if no rate is configured for the given source currency.
        """
        code = source_currency.upper()
        if code == self.reporting_currency:
            return Decimal("1.0")
        if code == "USD":
            return self.usd_to_reporting_fx_rate
        if code == "ETB":
            return self.etb_to_reporting_fx_rate
        raise ValueError(
            f"No FX rate configured for {code} → {self.reporting_currency}. "
            f"Add a rate to config/settings.py before running the pipeline."
        )

    def ensure_directories(self) -> None:
        """Create runtime directories if they do not exist."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton. Imported everywhere as `from config.settings import settings`.
settings = Settings()
