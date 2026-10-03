"""Streamlit dashboard for the financial analytics pipeline.

This module is the presentation layer. It contains:
    - layout
    - file upload widgets
    - a button to run the pipeline
    - formatting of results

It does NOT contain business logic. All computation is delegated to:
    - src.pipeline.run_pipeline (the pipeline itself)
    - src.reporting.dashboard_data (query helpers)
    - src.reporting.kpi_ribbon (display KPIs)
    - src.reporting.roas (ROAS classification)
    - src.reporting.export (CSV generation)

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import streamlit as st
from config.settings import Settings
from src.exceptions import PipelineError
from src.pipeline import run_pipeline
from src.reporting.dashboard_data import (
    get_date_range,
    load_model,
    model_exists,
)
from src.reporting.export import model_to_csv_bytes
from src.reporting.kpi_ribbon import RibbonKPIs, compute_ribbon
from src.reporting.roas import category_to_streamlit_delta, classify_roas
from src.utils.logging_config import configure_logging

# ---------------------------------------------------------------------- #
# Configuration                                                           #
# ---------------------------------------------------------------------- #

SQL_DIR = Path(__file__).parent / "sql"

if "logging_configured" not in st.session_state:
    configure_logging(level="INFO", log_dir=Path("logs"))
    st.session_state["logging_configured"] = True


# ---------------------------------------------------------------------- #
# Page setup                                                              #
# ---------------------------------------------------------------------- #

st.set_page_config(
    page_title="E-commerce Financial Analytics",
    page_icon="📊",
    layout="wide",
)


# ---------------------------------------------------------------------- #
# Session state                                                           #
# ---------------------------------------------------------------------- #

if "settings" not in st.session_state:
    st.session_state["settings"] = Settings()

if "pipeline_ran" not in st.session_state:
    st.session_state["pipeline_ran"] = False


# ---------------------------------------------------------------------- #
# Upload section                                                          #
# ---------------------------------------------------------------------- #

st.title("E-commerce Financial Analytics")
st.caption(
    "Upload a Shopify CSV and a Meta Ads CSV to generate a unified daily "
    "financial model. All monetary values are reported in the configured "
    "reporting currency."
)

settings: Settings = st.session_state["settings"]

model_ready = model_exists(settings) and st.session_state["pipeline_ran"]

if model_ready:
    st.success(
        "A model is loaded. Scroll down to see results, or upload new files " "to rebuild it."
    )

st.subheader("1. Upload source data")

col_shopify, col_meta = st.columns(2)

with col_shopify:
    shopify_file = st.file_uploader(
        "Shopify CSV",
        type=["csv"],
        key="shopify_uploader",
        help="The raw Shopify export. Required columns: Order ID, Created at, "
        "Financial Status, Gross Amount, Discount Amount, Net Amount, "
        "Taxes, Shipping fees, Currency.",
    )

with col_meta:
    meta_file = st.file_uploader(
        "Meta Ads CSV",
        type=["csv"],
        key="meta_uploader",
        help="The raw Meta Ads Manager export. Required columns: Reporting Start, "
        "Reporting End, Amount Spent. Optional: Campaign Name, Impressions, "
        "Link Clicks.",
    )

run_disabled = shopify_file is None or meta_file is None

if st.button(
    "Run Financial Analysis",
    type="primary",
    disabled=run_disabled,
    help="Both files are required." if run_disabled else None,
):
    with st.spinner("Processing data…"):
        shopify_path: Path | None = None
        meta_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb", suffix=".csv", delete=False, prefix="shopify_"
            ) as shopify_tmp:
                shopify_tmp.write(shopify_file.getvalue())
                shopify_path = Path(shopify_tmp.name)

            with NamedTemporaryFile(
                mode="wb", suffix=".csv", delete=False, prefix="meta_"
            ) as meta_tmp:
                meta_tmp.write(meta_file.getvalue())
                meta_path = Path(meta_tmp.name)

            result = run_pipeline(
                shopify_csv=shopify_path,
                meta_csv=meta_path,
                settings=settings,
                sql_dir=SQL_DIR,
            )

            st.session_state["pipeline_ran"] = True
            st.session_state["last_result"] = result
            st.success(
                f"Pipeline completed. Date range: " f"{result.dates_min} .. {result.dates_max}"
            )

        except PipelineError as exc:
            st.error(f"Pipeline failed: {exc}")
            st.exception(exc)
        finally:
            for p in (shopify_path, meta_path):
                if p is not None and p.exists():
                    with contextlib.suppress(OSError):
                        p.unlink()


# ---------------------------------------------------------------------- #
# Results section                                                         #
# ---------------------------------------------------------------------- #

if not (model_exists(settings) and st.session_state["pipeline_ran"]):
    st.info("Upload both files and click **Run Financial Analysis** to see results.")
    st.stop()


# --- Date range selector ------------------------------------------------- #

full_range = get_date_range(settings)
if full_range is None:
    st.warning("The model exists but contains no rows.")
    st.stop()

date_from, date_to = st.date_input(
    "Date range",
    value=full_range,
    min_value=full_range[0],
    max_value=full_range[1],
)

model = load_model(settings=settings, date_from=date_from, date_to=date_to)

if model.empty:
    st.warning("No data in the selected date range.")
    st.stop()


# --- KPI ribbon ---------------------------------------------------------- #

ribbon: RibbonKPIs = compute_ribbon(model, settings=settings)

st.subheader("2. Executive summary")

row1 = st.columns(4)
row1[0].metric(
    "Estimated Contribution Margin",
    f"{ribbon.total_contribution_margin:,.0f} {ribbon.reporting_currency}",
    help="Net revenue - Meta ad spend - estimated COGS (40% of gross). "
    "Excludes fulfillment, payment processing, and non-Meta marketing.",
)
row1[1].metric(
    "Profit Margin %",
    f"{ribbon.profit_margin * 100:.1f}%" if ribbon.profit_margin is not None else "—",
    help="Contribution margin ÷ net revenue. Undefined when net revenue is 0.",
)
roas_category = classify_roas(ribbon.blended_roas, settings=settings)
row1[2].metric(
    "Blended ROAS",
    f"{ribbon.blended_roas:.2f}" if ribbon.blended_roas is not None else "—",
    delta=category_to_streamlit_delta(roas_category),
    help="Period net revenue ÷ period Meta ad spend. Undefined when ad spend is 0. "
    "Colour thresholds are client-defined.",
)
row1[3].metric(
    "Meta Spend / Net Revenue",
    f"{ribbon.meta_spend_ratio:.2f}" if ribbon.meta_spend_ratio is not None else "—",
    help="Client-requested ratio. NOTE: this is the inverse of the industry-"
    "standard MER and includes only Meta spend, not all marketing channels.",
)

row2 = st.columns(4)
row2[0].metric(
    "Total Net Revenue",
    f"{ribbon.total_net_revenue:,.0f} {ribbon.reporting_currency}",
    help="Sum of net_amount across the selected period.",
)
row2[1].metric(
    "Total Ad Spend",
    f"{ribbon.total_ad_spend:,.0f} {ribbon.reporting_currency}",
    help="Sum of Meta ad spend, converted to the reporting currency.",
)
row2[2].metric(
    "Orders",
    f"{ribbon.total_orders:,}",
    help="Count of distinct orders with a revenue-recognized status.",
)
row2[3].metric(
    "Admin Hours Saved",
    f"{ribbon.administrative_hours_saved:.1f}",
    help="Estimated. Based on a 4-hour-per-week manual baseline, prorated "
    "to the selected date range.",
)


# --- Time series chart --------------------------------------------------- #

st.subheader("3. Daily trend")

# Design note: Net Profit and Ad Spend have different scales in a typical
# dataset. We plot them as two lines on a shared axis if their ranges are
# within an order of magnitude; otherwise we use two stacked charts. For
# simplicity in v1, we use two separate plots stacked vertically. This avoids
# the "misleading dual-axis" problem entirely.
chart_df = model.copy()
chart_df["calendar_date"] = pd.to_datetime(chart_df["calendar_date"])
chart_df = chart_df.set_index("calendar_date")

st.markdown("**Daily Net Profit (contribution margin)**")
st.line_chart(
    chart_df["contribution_margin"],
    color="#2e7d32",
    height=200,
)

st.markdown("**Daily Meta Ad Spend**")
st.line_chart(
    chart_df["ad_spend"],
    color="#c62828",
    height=200,
)


# --- Export -------------------------------------------------------------- #

st.subheader("4. Export")

csv_bytes = model_to_csv_bytes(model)
st.download_button(
    label="Download daily model as CSV",
    data=csv_bytes,
    file_name=f"daily_financial_model_{date_from}_to_{date_to}.csv",
    mime="text/csv",
)
