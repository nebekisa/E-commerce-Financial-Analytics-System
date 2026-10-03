"""Tests for src/transformation/shopify_transform.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from config.settings import Settings
from src.transformation.shopify_transform import transform_shopify
from src.validation.validators import DQReport


def _settings(**overrides: object) -> Settings:
    defaults = dict(
        reporting_currency="ETB",
        reporting_timezone="Africa/Addis_Ababa",
        shopify_source_currency="ETB",
        etb_to_reporting_fx_rate=Decimal("1.0"),
        revenue_statuses=frozenset({"paid", "partially_paid", "partially_refunded"}),
        excluded_statuses=frozenset({"pending", "cancelled", "refunded", "voided"}),
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _df(rows: list[dict[str, str]]) -> pd.DataFrame:
    """Build a canonical Shopify DataFrame from a list of dicts."""
    df = pd.DataFrame(rows, dtype="string")
    # Ensure all canonical columns exist even if a row omits them.
    for col in [
        "order_id",
        "created_at",
        "financial_status",
        "gross_amount",
        "discount_amount",
        "net_amount",
        "taxes",
        "shipping_fees",
        "currency",
    ]:
        if col not in df.columns:
            df[col] = pd.NA
    return df


# ---------------------------------------------------------------------- #
# Happy path                                                              #
# ---------------------------------------------------------------------- #


def test_single_valid_order() -> None:
    df = _df(
        [
            {
                "order_id": "1001",
                "created_at": "2026-09-01 09:15:00 UTC",
                "financial_status": "paid",
                "gross_amount": "1500.00",
                "discount_amount": "100.00",
                "net_amount": "1400.00",
                "taxes": "210.00",
                "shipping_fees": "50.00",
                "currency": "ETB",
            }
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert len(out) == 1
    row = out.iloc[0]
    assert row["order_id"] == "1001"
    assert row["calendar_date"] == date(2026, 9, 1)
    assert row["gross_amount"] == 1500.0
    assert row["net_amount"] == 1400.0
    assert row["reporting_currency"] == "ETB"
    assert report.rows_rejected == 0


def test_multiple_orders_same_day() -> None:
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "15.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
            {
                "order_id": "2",
                "created_at": "2026-09-01 15:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "200.00",
                "discount_amount": "0.00",
                "net_amount": "200.00",
                "taxes": "30.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
        ]
    )
    out, _ = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert len(out) == 2
    assert all(d == date(2026, 9, 1) for d in out["calendar_date"])


# ---------------------------------------------------------------------- #
# Timezone boundary                                                       #
# ---------------------------------------------------------------------- #


def test_timezone_crosses_midnight() -> None:
    """23:30 UTC on Sep 1 is 02:30 Addis on Sep 2. This is the trap."""
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 23:30:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, _ = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert out.iloc[0]["calendar_date"] == date(2026, 9, 2)


def test_timezone_stays_same_day() -> None:
    """20:30 UTC on Sep 1 is 23:30 Addis on Sep 1."""
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 20:30:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, _ = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert out.iloc[0]["calendar_date"] == date(2026, 9, 1)


# ---------------------------------------------------------------------- #
# Status classification                                                   #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status,expected_kept",
    [
        ("paid", True),
        ("Paid", True),
        ("partially_paid", True),
        ("partially_refunded", True),
        ("pending", False),
        ("cancelled", False),
        ("refunded", False),
        ("voided", False),
    ],
)
def test_status_classification(status: str, expected_kept: bool) -> None:
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": status,
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert (len(out) == 1) == expected_kept
    if not expected_kept:
        assert report.rejection_reasons.get("excluded_status", 0) == 1


def test_unknown_status_excluded_with_warning(caplog) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "disputed",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert len(out) == 0
    assert report.rejection_reasons.get("excluded_status", 0) == 1
    assert any("Unknown Shopify financial_status" in r.message for r in caplog.records)


# ---------------------------------------------------------------------- #
# Money parsing rejection                                                 #
# ---------------------------------------------------------------------- #


def test_unparseable_gross_amount_rejected() -> None:
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "not_a_number",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert len(out) == 0
    assert report.rejection_reasons.get("invalid_money", 0) == 1


def test_unparseable_discount_treated_as_zero() -> None:
    """Optional money columns become 0, not rejection."""
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "",
                "net_amount": "100.00",
                "taxes": "",
                "shipping_fees": "",
                "currency": "ETB",
            }
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert len(out) == 1
    assert out.iloc[0]["discount_amount"] == 0.0
    assert out.iloc[0]["taxes"] == 0.0
    assert out.iloc[0]["shipping_fees"] == 0.0


def test_transform_updates_report_counts() -> None:
    """After transform, rows_accepted + rows_rejected must equal rows_received."""
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
            {
                "order_id": "2",
                "created_at": "2026-09-01 10:00:00 UTC",
                "financial_status": "cancelled",
                "gross_amount": "200.00",
                "discount_amount": "0.00",
                "net_amount": "200.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
            {
                "order_id": "3",
                "created_at": "2026-09-01 11:00:00 UTC",
                "financial_status": "refunded",
                "gross_amount": "300.00",
                "discount_amount": "0.00",
                "net_amount": "300.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
        ]
    )
    report = DQReport(source="shopify", rows_received=3)
    out, report = transform_shopify(df, settings=_settings(), report=report)

    assert len(out) == 1
    assert report.rows_accepted == 1
    assert report.rows_rejected == 2
    assert report.rows_accepted + report.rows_rejected == report.rows_received


def test_unparseable_created_at_rejected() -> None:
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "not-a-date",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert len(out) == 0
    assert report.rejection_reasons.get("invalid_created_at", 0) == 1


# ---------------------------------------------------------------------- #
# Currency conversion                                                     #
# ---------------------------------------------------------------------- #


def test_currency_conversion_applied() -> None:
    """Shopify revenue in USD converted to ETB at configured rate."""
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "10.00",
                "net_amount": "90.00",
                "taxes": "13.50",
                "shipping_fees": "5.00",
                "currency": "USD",
            }
        ]
    )
    settings = _settings(
        reporting_currency="ETB",
        shopify_source_currency="USD",
        usd_to_reporting_fx_rate=Decimal("130.0"),
    )
    out, _ = transform_shopify(df, settings=settings, report=DQReport(source="shopify"))
    assert out.iloc[0]["gross_amount"] == 13000.0
    assert out.iloc[0]["net_amount"] == 11700.0
    assert out.iloc[0]["reporting_currency"] == "ETB"


def test_no_conversion_when_currencies_match() -> None:
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "0.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            }
        ]
    )
    out, _ = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    assert out.iloc[0]["gross_amount"] == 100.0


# ---------------------------------------------------------------------- #
# Combined / integration-style                                            #
# ---------------------------------------------------------------------- #


def test_mixed_statuses_and_values() -> None:
    df = _df(
        [
            {
                "order_id": "1",
                "created_at": "2026-09-01 09:00:00 UTC",
                "financial_status": "paid",
                "gross_amount": "100.00",
                "discount_amount": "0.00",
                "net_amount": "100.00",
                "taxes": "15.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
            {
                "order_id": "2",
                "created_at": "2026-09-01 10:00:00 UTC",
                "financial_status": "cancelled",
                "gross_amount": "200.00",
                "discount_amount": "0.00",
                "net_amount": "200.00",
                "taxes": "30.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
            {
                "order_id": "3",
                "created_at": "not-a-date",
                "financial_status": "paid",
                "gross_amount": "300.00",
                "discount_amount": "0.00",
                "net_amount": "300.00",
                "taxes": "45.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
            {
                "order_id": "4",
                "created_at": "2026-09-02 12:00:00 UTC",
                "financial_status": "partially_refunded",
                "gross_amount": "400.00",
                "discount_amount": "0.00",
                "net_amount": "300.00",
                "taxes": "60.00",
                "shipping_fees": "0.00",
                "currency": "ETB",
            },
        ]
    )
    out, report = transform_shopify(df, settings=_settings(), report=DQReport(source="shopify"))
    # Order 1: kept. Order 2: excluded_status. Order 3: invalid_created_at.
    # Order 4: kept (partially_refunded is recognized).
    assert len(out) == 2
    kept_ids = set(out["order_id"])
    assert kept_ids == {"1", "4"}
    assert report.rejection_reasons.get("excluded_status", 0) == 1
    assert report.rejection_reasons.get("invalid_created_at", 0) == 1
