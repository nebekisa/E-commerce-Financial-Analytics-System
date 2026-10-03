"""Tests for src/transformation/meta_transform.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from config.settings import Settings
from src.transformation.meta_transform import transform_meta_ads
from src.validation.validators import DQReport


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        reporting_currency="ETB",
        reporting_timezone="Africa/Addis_Ababa",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("130.0"),
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _df(rows: list[dict[str, str]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, dtype="string")
    for col in [
        "reporting_start",
        "reporting_end",
        "campaign_name",
        "spend_amount",
        "impressions",
        "link_clicks",
    ]:
        if col not in df.columns:
            df[col] = pd.NA
    return df


# ---------------------------------------------------------------------- #
# Happy path                                                              #
# ---------------------------------------------------------------------- #


def test_single_day_row() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "Summer Sale",
                "spend_amount": "120.50",
                "impressions": "45000",
                "link_clicks": "850",
            }
        ]
    )
    out, report = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 1
    row = out.iloc[0]
    assert row["calendar_date"] == date(2026, 9, 1)
    assert row["campaign_name"] == "Summer Sale"
    # 120.50 USD x 130 = 15665.0 ETB
    assert row["spend_amount"] == pytest.approx(15665.0)
    assert row["impressions"] == 45000
    assert row["link_clicks"] == 850
    assert row["reporting_currency"] == "ETB"
    assert report.rows_rejected == 0


# ---------------------------------------------------------------------- #
# Multi-day rejection                                                     #
# ---------------------------------------------------------------------- #


def test_multi_day_interval_rejected(caplog) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-07",
                "campaign_name": "Weekly Rollup",
                "spend_amount": "800.00",
                "impressions": "320000",
                "link_clicks": "5500",
            }
        ]
    )
    out, report = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 0
    assert report.rejection_reasons.get("multi_day_interval", 0) == 1
    assert any("multi-day" in r.message.lower() for r in caplog.records)


def test_mixed_single_and_multi_day() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "A",
                "spend_amount": "100.00",
                "impressions": "1000",
                "link_clicks": "50",
            },
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-07",
                "campaign_name": "B",
                "spend_amount": "700.00",
                "impressions": "7000",
                "link_clicks": "350",
            },
            {
                "reporting_start": "2026-09-02",
                "reporting_end": "2026-09-02",
                "campaign_name": "C",
                "spend_amount": "200.00",
                "impressions": "2000",
                "link_clicks": "100",
            },
        ]
    )
    out, report = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 2
    assert set(out["campaign_name"]) == {"A", "C"}
    assert report.rejection_reasons.get("multi_day_interval", 0) == 1


# ---------------------------------------------------------------------- #
# Invalid dates                                                           #
# ---------------------------------------------------------------------- #


def test_unparseable_start_rejected() -> None:
    df = _df(
        [
            {
                "reporting_start": "not-a-date",
                "reporting_end": "2026-09-01",
                "campaign_name": "A",
                "spend_amount": "100.00",
                "impressions": "1000",
                "link_clicks": "50",
            }
        ]
    )
    out, report = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 0
    assert report.rejection_reasons.get("invalid_meta_date", 0) == 1


def test_unparseable_end_rejected() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "not-a-date",
                "campaign_name": "A",
                "spend_amount": "100.00",
                "impressions": "1000",
                "link_clicks": "50",
            }
        ]
    )
    out, report = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 0
    assert report.rejection_reasons.get("invalid_meta_date", 0) == 1


# ---------------------------------------------------------------------- #
# Null campaign                                                           #
# ---------------------------------------------------------------------- #


def test_null_campaign_name_preserved() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "",
                "spend_amount": "100.00",
                "impressions": "1000",
                "link_clicks": "50",
            }
        ]
    )
    out, _ = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 1
    assert pd.isna(out.iloc[0]["campaign_name"])


# ---------------------------------------------------------------------- #
# Null tracking                                                           #
# ---------------------------------------------------------------------- #


def test_null_impressions_and_clicks_preserved() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "A",
                "spend_amount": "100.00",
                "impressions": "",
                "link_clicks": "",
            }
        ]
    )
    out, _ = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 1
    assert pd.isna(out.iloc[0]["impressions"])
    assert pd.isna(out.iloc[0]["link_clicks"])


# ---------------------------------------------------------------------- #
# Zero spend                                                              #
# ---------------------------------------------------------------------- #


def test_zero_spend_accepted() -> None:
    """Zero spend is a valid value, not a missing one."""
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "A",
                "spend_amount": "0.00",
                "impressions": "0",
                "link_clicks": "0",
            }
        ]
    )
    out, report = transform_meta_ads(df, settings=_settings(), report=DQReport(source="meta_ads"))
    assert len(out) == 1
    assert out.iloc[0]["spend_amount"] == 0.0
    assert report.rows_rejected == 0


# ---------------------------------------------------------------------- #
# Currency conversion                                                     #
# ---------------------------------------------------------------------- #


def test_spend_converted_to_reporting_currency() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "A",
                "spend_amount": "100.00",
                "impressions": "1000",
                "link_clicks": "50",
            }
        ]
    )
    settings = _settings(
        reporting_currency="ETB",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("135.0"),
    )
    out, _ = transform_meta_ads(df, settings=settings, report=DQReport(source="meta_ads"))
    assert out.iloc[0]["spend_amount"] == pytest.approx(13500.0)


def test_no_conversion_when_currencies_match() -> None:
    df = _df(
        [
            {
                "reporting_start": "2026-09-01",
                "reporting_end": "2026-09-01",
                "campaign_name": "A",
                "spend_amount": "100.00",
                "impressions": "1000",
                "link_clicks": "50",
            }
        ]
    )
    settings = _settings(
        reporting_currency="USD",
        meta_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("1.0"),
    )
    out, _ = transform_meta_ads(df, settings=settings, report=DQReport(source="meta_ads"))
    assert out.iloc[0]["spend_amount"] == 100.0
