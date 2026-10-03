# E-commerce Financial Analytics System

A local, batch-oriented financial analytics pipeline for an independent
e-commerce brand. Takes Shopify order exports and Meta Ads Manager exports,
produces a daily financial model with contribution margin, ROAS, and other
KPIs, and serves them through a Streamlit dashboard or a CLI.

## Business problem

The client spent ~4 hours every weekend manually:

1. Downloading Shopify and Meta Ads CSV exports.
2. Cleaning them in Excel.
3. Matching dates.
4. Computing revenue, ad spend, and margin.
5. Building charts and a report.

This system replaces that workflow with a single command (or one button in
the dashboard). Runtime for a typical weekend's data is a few seconds.

## What it produces

A daily financial model with, for each calendar date:

- Revenue: gross, net, discounts, taxes, shipping fees
- Order count
- Ad spend, impressions, link clicks (from Meta)
- Estimated COGS (40% of gross by default, configurable)
- Estimated contribution margin
- Blended ROAS, Meta spend ratio, profit margin
- Reporting currency

The model is stored in DuckDB and can be exported to CSV. It's the single
source of truth for every downstream consumer: the CLI, the dashboard, and
any future scheduled job.

## Non-goals

- Real-time or streaming ingestion. This is a batch tool.
- Multi-currency Shopify orders. All orders are assumed to be in the
  source currency defined in config.
- Multi-user or cloud deployment. This is a single-user local tool.
- SKU-level margin. COGS is estimated as a flat percentage of gross.
- Attribution modeling. We report blended ROAS, not per-campaign
  attribution.

## Installation

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

Copy the example environment file:
cp .env.example .env

Edit .env to set:

    REPORTING_CURRENCY (default ETB)

    USD_TO_REPORTING_FX_RATE (default 130.0)

    COGS_PERCENTAGE (default 0.40)

    Any other values you need to override.

Usage
Command line
bash

python -m src \
    --shopify data/raw/shopify_export.csv \
    --meta data/raw/meta_export.csv

Options:
Flag	Description	Default
--shopify	Path to Shopify CSV	required
--meta	    Path to Meta Ads CSV	required
--database	Path to DuckDB file	data/processed/analytics.duckdb
--sql-dir	Directory of SQL model files	sql/
--reporting-currency	ISO 4217 currency code	from .env
--fx-rate	USD → reporting currency rate	from .env
--log-level	DEBUG, INFO, WARNING, ERROR, CRITICAL	from .env

Exit codes:
Code	Meaning
0	Success
2	Schema error (missing/extra columns, unreadable file)
3	Data quality threshold exceeded
4	Currency conversion error
5	Database error
6	Transformation error
7	Configuration error
99	Unexpected error (bug; inspect logs)
Dashboard
bash

streamlit run app.py

The browser opens to http://localhost:8501. Upload the two CSVs, click
Run Financial Analysis, and inspect or export the model.