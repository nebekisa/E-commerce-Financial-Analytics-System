"""Tests for src/reporting/kpi_ribbon.py."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest
from config.settings import Settings
from src.reporting.kpi_ribbon import compute_ribbon


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        reporting_currency="ETB",
        admin_hours_per_week=Decimal("4.0"),
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _empty_model() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "calendar_date": pd.Series([], dtype="datetime64[ns]"),
            "net_revenue": pd.Series([], dtype="float64"),
            "ad_spend": pd.Series([], dtype="float64"),
            "contribution_margin": pd.Series([], dtype="float64"),
            "orders": pd.Series([], dtype="int64"),
            "reporting_currency": pd.Series([], dtype="string"),
        }
    )


def _model(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["calendar_date"] = pd.to_datetime(df["calendar_date"])
    return df


# ---------------------------------------------------------------------- #
# Empty model                                                             #
# ---------------------------------------------------------------------- #


def test_empty_model_returns_zeroed_ribbon() -> None:
    r = compute_ribbon(_empty_model(), settings=_settings())
    assert r.total_net_revenue == 0.0
    assert r.total_ad_spend == 0.0
    assert r.total_contribution_margin == 0.0
    assert r.profit_margin is None
    assert r.blended_roas is None
    assert r.meta_spend_ratio is None
    assert r.total_orders == 0
    assert r.administrative_hours_saved == 0.0


# ---------------------------------------------------------------------- #
# Golden-dataset totals                                                   #
# ---------------------------------------------------------------------- #


def test_golden_totals() -> None:
    """Totals across the 5-day golden dataset.
    net_revenue = 3580, ad_spend = 19500, contribution = -17440, orders = 6.
    """
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 1400.0,
            "ad_spend": 9100.0,
            "contribution_margin": -8300.0,
            "orders": 2,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-02",
            "net_revenue": 950.0,
            "ad_spend": 5200.0,
            "contribution_margin": -4650.0,
            "orders": 2,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-03",
            "net_revenue": 600.0,
            "ad_spend": 3900.0,
            "contribution_margin": -3540.0,
            "orders": 1,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-04",
            "net_revenue": 630.0,
            "ad_spend": 0.0,
            "contribution_margin": 350.0,
            "orders": 1,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-05",
            "net_revenue": 0.0,
            "ad_spend": 1300.0,
            "contribution_margin": -1300.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings())
    assert r.total_net_revenue == pytest.approx(3580.0)
    assert r.total_ad_spend == pytest.approx(19500.0)
    assert r.total_contribution_margin == pytest.approx(-17440.0)
    assert r.total_orders == 6
    assert r.profit_margin == pytest.approx(-17440 / 3580)
    assert r.blended_roas == pytest.approx(3580 / 19500)
    assert r.meta_spend_ratio == pytest.approx(19500 / 3580)
    assert r.reporting_currency == "ETB"


# ---------------------------------------------------------------------- #
# Admin hours                                                             #
# ---------------------------------------------------------------------- #


def test_admin_hours_five_days() -> None:
    """5 days = 5/7 weeks; 4h/week baseline → 2.857 → 2.9 after rounding."""
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-05",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings())
    assert r.administrative_hours_saved == 2.9


def test_admin_hours_single_day() -> None:
    """1 day = 1/7 weeks; 4h/week baseline → 0.571 → 0.6 after rounding."""
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings())
    assert r.administrative_hours_saved == 0.6


def test_admin_hours_seven_days() -> None:
    """7 days = 1 week → exactly 4.0."""
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-07",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings())
    assert r.administrative_hours_saved == 4.0


def test_admin_hours_custom_baseline() -> None:
    """10 hours/week baseline over 7 days → exactly 10.0."""
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
        {
            "calendar_date": "2026-09-07",
            "net_revenue": 0.0,
            "ad_spend": 0.0,
            "contribution_margin": 0.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings(admin_hours_per_week=Decimal("10.0")))
    assert r.administrative_hours_saved == 10.0


# ---------------------------------------------------------------------- #
# Division guards                                                         #
# ---------------------------------------------------------------------- #


def test_zero_ad_spend_yields_none_roas() -> None:
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 100.0,
            "ad_spend": 0.0,
            "contribution_margin": 100.0,
            "orders": 1,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings())
    assert r.blended_roas is None
    assert r.meta_spend_ratio == 0.0  # 0 spend / 100 revenue


def test_zero_net_revenue_yields_none_ratios() -> None:
    rows = [
        {
            "calendar_date": "2026-09-01",
            "net_revenue": 0.0,
            "ad_spend": 100.0,
            "contribution_margin": -100.0,
            "orders": 0,
            "reporting_currency": "ETB",
        },
    ]
    r = compute_ribbon(_model(rows), settings=_settings())
    assert r.blended_roas == 0.0  # 0 revenue / 100 spend
    assert r.meta_spend_ratio is None
    assert r.profit_margin is None
