# Changelog

All notable changes to this project, organized by phase. This project
follows a phase-based development model (see the phase notes in the
project history); version numbers are not yet applied.

## Phase 11 — Documentation

- `README.md`, `docs/ARCHITECTURE.md`, `docs/KPI_DEFINITIONS.md`,
  `docs/KNOWN_LIMITATIONS.md`.
- `Makefile` with convenience targets (`test`, `lint`, `format`, `run`).

## Phase 10 — Production engineering review

No code changes. Review findings documented in the phase notes.

## Phase 9 — End-to-end integration test

- `tests/test_end_to_end.py` covering the full pipeline as a subprocess.
- **Bug fix:** `daily_financial_model` changed from a view to a
  materialized table. Views that depend on session variables
  (`getvariable('cogs_percentage')`) produced NULLs when read from a fresh
  connection.
- CLI: replaced non-ASCII box-drawing characters with ASCII to avoid
  `UnicodeEncodeError` on Windows codepage 1252.
- CLI: added `_ensure_utf8_stdout` to force UTF-8 on stdout/stderr.

## Phase 8c — Streamlit smoke tests

- `tests/test_app_smoke.py` using `streamlit.testing.v1.AppTest`.
- Scoped `filterwarnings` in `pyproject.toml` to error only on
  deprecations from `src`/`config`/`tests`; library deprecations are
  warnings.

## Phase 8b — Time series, ROAS color, CSV export

- `src/reporting/roas.py` and `src/reporting/export.py`.
- Dashboard: two stacked line charts (contribution margin, ad spend);
  colored ROAS delta; download button.
- `app.py` updated to use the new modules.

## Phase 8a — Streamlit dashboard skeleton

- `app.py`: upload flow, pipeline invocation, KPI ribbon, DQ banner.
- `src/reporting/dashboard_data.py`: `load_model`, `get_date_range`,
  `model_exists`.
- `src/reporting/kpi_ribbon.py`: `compute_ribbon`.

## Phase 7 — Pipeline orchestrator and CLI

- `src/pipeline.py`: `run_pipeline`, `PipelineResult`.
- `src/cli.py`, `src/__main__.py`.
- Fixed: `DQReport` counts now updated by the transform stage; the
  `rows_received < len(df)` guard handles standalone calls.

## Phase 6 — Golden dataset

- `tests/fixtures/golden_shopify.csv`, `tests/fixtures/golden_meta.csv`.
- `tests/test_golden_dataset.py` with hand-calculated expected values.
- **Bug fix:** `partially_refunded` added to the default
  `revenue_statuses`. It was previously treated as an unknown status.

## Phase 5 — DuckDB storage and SQL financial model

- `src/database/duckdb_engine.py`.
- `sql/01_shopify_daily.sql`, `02_meta_daily.sql`, `03_date_spine.sql`,
  `04_daily_financial_model.sql`.
- Fixed: `generate_series` requires TIMESTAMP bounds, not DATE;
  `COALESCE` requires explicit type cast; `ORDER BY` needed on the date
  spine.

## Phase 4b — Source transforms

- `src/transformation/shopify_transform.py`,
  `src/transformation/meta_transform.py`.

## Phase 4a — Cleaning and FX

- `src/transformation/cleaning.py`: money, dates, statuses.
- `src/fx/converter.py`.

## Phase 3 — Meta Ads ingestion

- `src/ingestion/meta_ads.py`.
- `tests/fixtures/meta_clean.csv`, `meta_dirty.csv`.
- Optional columns (`campaign_name`, `impressions`, `link_clicks`) are
  nullable and carried forward.

## Phase 2 — Shopify ingestion

- `src/ingestion/shopify.py`.
- `src/validation/header_mapper.py`, `schemas.py`, `validators.py`.
- Fixtures for clean and adversarial inputs.

## Phase 1 — Project skeleton

- `config/settings.py`, `src/exceptions.py`,
  `src/utils/logging_config.py`.

## Phase 0 — Architecture

- Layered design, SQL-first modeling, currency strategy, timezone
  strategy, data quality strategy.