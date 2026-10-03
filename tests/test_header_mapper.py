"""Tests for src/validation/header_mapper.py."""

from __future__ import annotations

import pandas as pd
import pytest
from src.exceptions import SchemaError
from src.validation.header_mapper import ColumnSpec, map_headers, normalize_header
from src.validation.schemas import SHOPIFY_SPECS

# ---------------------------------------------------------------------- #
# normalize_header                                                        #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Created At ", "created_at"),
        ("CREATED AT", "created_at"),
        ("created  at", "created_at"),
        ("Gross Amount ($)", "gross_amount"),
        ("  ORDER--ID  ", "order_id"),
        ("Shipping fees", "shipping_fees"),
        ("shipping-fees", "shipping_fees"),
        ("", ""),
    ],
)
def test_normalize_header(raw: str, expected: str) -> None:
    assert normalize_header(raw) == expected


# ---------------------------------------------------------------------- #
# map_headers                                                             #
# ---------------------------------------------------------------------- #


def test_map_headers_renames_aliases() -> None:
    df = pd.DataFrame(
        columns=[
            "Created At",
            "Order ID",
            "Financial Status",
            "Gross Amount",
            "Discount Amount",
            "Net Amount",
            "Taxes",
            "Shipping fees",
            "Currency",
        ]
    )
    out, report = map_headers(df, SHOPIFY_SPECS)
    assert set(out.columns) == {
        "order_id",
        "created_at",
        "financial_status",
        "gross_amount",
        "discount_amount",
        "net_amount",
        "taxes",
        "shipping_fees",
        "currency",
    }
    assert "Created At" in report.renamed
    assert report.renamed["Created At"] == "created_at"
    assert report.missing_required == []
    assert report.unexpected == []


def test_map_headers_already_canonical() -> None:
    df = pd.DataFrame(
        columns=[
            "order_id",
            "created_at",
            "financial_status",
            "gross_amount",
            "discount_amount",
            "net_amount",
            "taxes",
            "shipping_fees",
            "currency",
        ]
    )
    out, report = map_headers(df, SHOPIFY_SPECS)
    assert report.renamed == {}
    assert report.missing_required == []


def test_map_headers_missing_required_raises() -> None:
    df = pd.DataFrame(columns=["Order ID", "Created At", "Financial Status"])
    with pytest.raises(SchemaError) as exc_info:
        map_headers(df, SHOPIFY_SPECS)
    assert "Missing required columns" in str(exc_info.value)
    assert "gross_amount" in exc_info.value.context["missing"]


def test_map_headers_unexpected_columns_are_reported() -> None:
    df = pd.DataFrame(
        columns=[
            "order_id",
            "created_at",
            "financial_status",
            "gross_amount",
            "discount_amount",
            "net_amount",
            "taxes",
            "shipping_fees",
            "currency",
            "promo_code",
        ]
    )
    _, report = map_headers(df, SHOPIFY_SPECS)
    assert report.unexpected == ["promo_code"]


def test_map_headers_duplicate_raw_headers_raise() -> None:
    # Simulate pandas' duplicate-suffix behavior.
    df = pd.DataFrame(
        columns=[
            "order_id",
            "created_at",
            "financial_status",
            "gross_amount",
            "discount_amount",
            "net_amount",
            "taxes",
            "shipping_fees",
            "currency",
            "gross_amount",  # duplicate
        ]
    )
    # pandas will have renamed the second one to "gross_amount.1"
    df.columns = [
        "order_id",
        "created_at",
        "financial_status",
        "gross_amount",
        "discount_amount",
        "net_amount",
        "taxes",
        "shipping_fees",
        "currency",
        "gross_amount.1",
    ]
    with pytest.raises(SchemaError, match="Duplicate column names"):
        map_headers(df, SHOPIFY_SPECS)


def test_map_headers_two_raw_headers_normalize_to_same() -> None:
    df = pd.DataFrame(
        columns=[
            "Created At",
            "created_at",  # both normalize to "created_at"
            "Order ID",
            "Financial Status",
            "Gross Amount",
            "Discount Amount",
            "Net Amount",
            "Taxes",
            "Shipping fees",
            "Currency",
        ]
    )
    with pytest.raises(SchemaError, match="normalize to the same name"):
        map_headers(df, SHOPIFY_SPECS)


def test_map_headers_optional_missing_is_fine() -> None:
    """Optional columns (like Meta's campaign_name) can be absent."""
    specs = [
        ColumnSpec(canonical="reporting_start", aliases=frozenset(), required=True),
        ColumnSpec(canonical="spend_amount", aliases=frozenset(), required=True),
        ColumnSpec(canonical="campaign_name", aliases=frozenset(), required=False),
    ]
    df = pd.DataFrame(columns=["reporting_start", "spend_amount"])
    out, report = map_headers(df, specs)
    assert report.missing_required == []
    assert "campaign_name" not in out.columns
