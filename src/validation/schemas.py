"""Canonical schema definitions for all input sources.

Each schema is a list of ColumnSpec instances. Downstream code refers to the
canonical names only; raw header names never escape the header-mapping layer.
"""

from __future__ import annotations

from src.validation.header_mapper import ColumnSpec

# ---------------------------------------------------------------------- #
# Shopify                                                                 #
# ---------------------------------------------------------------------- #

SHOPIFY_SPECS: list[ColumnSpec] = [
    ColumnSpec(
        canonical="order_id",
        aliases=frozenset({"orderid", "id", "order_number"}),
        required=True,
    ),
    ColumnSpec(
        canonical="created_at",
        aliases=frozenset({"created", "order_date", "date"}),
        required=True,
    ),
    ColumnSpec(
        canonical="financial_status",
        aliases=frozenset({"status", "payment_status"}),
        required=True,
    ),
    ColumnSpec(
        canonical="gross_amount",
        aliases=frozenset({"gross", "gross_sales", "subtotal"}),
        required=True,
    ),
    ColumnSpec(
        canonical="discount_amount",
        aliases=frozenset({"discount", "discounts", "discounts_amount"}),
        required=True,
    ),
    ColumnSpec(
        canonical="net_amount",
        aliases=frozenset({"net", "net_sales", "total"}),
        required=True,
    ),
    ColumnSpec(
        canonical="taxes",
        aliases=frozenset({"tax", "tax_amount", "total_tax"}),
        required=True,
    ),
    ColumnSpec(
        canonical="shipping_fees",
        aliases=frozenset({"shipping", "shipping_fee", "shipping_amount"}),
        required=True,
    ),
    ColumnSpec(
        canonical="currency",
        aliases=frozenset({"currency_code", "order_currency"}),
        required=True,
    ),
]

# ---------------------------------------------------------------------- #
# Meta Ads (declared now, used in Phase 3)                                #
# ---------------------------------------------------------------------- #

META_SPECS: list[ColumnSpec] = [
    ColumnSpec(
        canonical="reporting_start",
        aliases=frozenset({"report_start", "date_start", "start_date"}),
        required=True,
    ),
    ColumnSpec(
        canonical="reporting_end",
        aliases=frozenset({"report_end", "date_end", "end_date"}),
        required=True,
    ),
    ColumnSpec(
        canonical="campaign_name",
        aliases=frozenset({"campaign"}),
        required=False,
    ),
    ColumnSpec(
        canonical="spend_amount",
        aliases=frozenset({"amount_spent", "spend", "cost", "amount_spent_usd"}),
        required=True,
    ),
    ColumnSpec(
        canonical="impressions",
        aliases=frozenset({"impression", "impressions_count"}),
        required=False,
    ),
    ColumnSpec(
        canonical="link_clicks",
        aliases=frozenset({"clicks", "link_click", "link_clicks_count"}),
        required=False,
    ),
]
