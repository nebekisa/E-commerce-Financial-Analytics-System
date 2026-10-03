"""Compute display KPIs from the daily model.

The dashboard shows a ribbon of top-line numbers at the top. Those numbers
are aggregates across the (filtered) date range. They are computed here, not
in app.py, so they can be tested without Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from config.settings import Settings


@dataclass(frozen=True)
class RibbonKPIs:
    """The KPI ribbon values displayed at the top of the dashboard."""

    total_net_revenue: float
    total_ad_spend: float
    total_contribution_margin: float
    profit_margin: float | None  # None when net_revenue = 0
    blended_roas: float | None  # None when ad_spend = 0
    meta_spend_ratio: float | None  # None when net_revenue = 0
    total_orders: int
    administrative_hours_saved: float
    reporting_currency: str


def compute_ribbon(
    model: pd.DataFrame,
    *,
    settings: Settings,
) -> RibbonKPIs:
    """Aggregate the daily model into a single set of ribbon KPIs.

    All formulas match the SQL model's daily formulas, but aggregated over the
    whole period. Uses the same guards (division by zero → None, not inf).

    Args:
        model: Output of load_model(...). May be empty.
        settings: Used for admin_hours_per_week and reporting_currency.
    """
    if model.empty:
        return RibbonKPIs(
            total_net_revenue=0.0,
            total_ad_spend=0.0,
            total_contribution_margin=0.0,
            profit_margin=None,
            blended_roas=None,
            meta_spend_ratio=None,
            total_orders=0,
            administrative_hours_saved=0.0,
            reporting_currency=settings.reporting_currency,
        )

    total_net_revenue = float(model["net_revenue"].sum())
    total_ad_spend = float(model["ad_spend"].sum())
    total_contribution_margin = float(model["contribution_margin"].sum())
    total_orders = int(model["orders"].sum())

    profit_margin = total_contribution_margin / total_net_revenue if total_net_revenue > 0 else None
    blended_roas = total_net_revenue / total_ad_spend if total_ad_spend > 0 else None
    meta_spend_ratio = total_ad_spend / total_net_revenue if total_net_revenue > 0 else None

    admin_hours = _compute_admin_hours_saved(model, settings)

    return RibbonKPIs(
        total_net_revenue=total_net_revenue,
        total_ad_spend=total_ad_spend,
        total_contribution_margin=total_contribution_margin,
        profit_margin=profit_margin,
        blended_roas=blended_roas,
        meta_spend_ratio=meta_spend_ratio,
        total_orders=total_orders,
        administrative_hours_saved=admin_hours,
        reporting_currency=settings.reporting_currency,
    )


def _compute_admin_hours_saved(model: pd.DataFrame, settings: Settings) -> float:
    """Estimate hours saved by automating the manual process.

    Formula: admin_hours_per_week x (days_in_range / 7), rounded to 1 decimal.

    Edge cases:
        * Empty model → 0.0
        * Single-day range → admin_hours_per_week / 7 (e.g., 0.6 for a 4h/week baseline)
        * Partial weeks are prorated, not rounded up.

    This is an *estimate*. The client-provided baseline (4 hours/week) is
    surfaced in the UI as "estimated" to avoid implying precision the number
    doesn't have.
    """
    if model.empty:
        return 0.0

    min_date: date = model["calendar_date"].min().date()
    max_date: date = model["calendar_date"].max().date()
    days = (max_date - min_date).days + 1  # inclusive
    weeks = days / 7.0

    hours = float(settings.admin_hours_per_week) * weeks
    return round(hours, 1)
