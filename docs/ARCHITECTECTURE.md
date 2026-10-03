
---

## 3. `docs/ARCHITECTURE.md`

```markdown
# Architecture

## Overview

The system is a batch ETL pipeline with a SQL modeling layer and two
presentation surfaces (CLI, Streamlit). It's designed for a single user
running it locally on a laptop or a small server.

## Layered design
┌─────────────────────────────────────────────────────────┐
│ PRESENTATION │
│ app.py (Streamlit) │ src/cli.py │
│ No data logic. Layout, uploads, formatting only. │
└────────────────────────┬────────────────────────────────┘
│ calls
┌────────────────────────▼────────────────────────────────┐
│ ORCHESTRATION │
│ src/pipeline.py │
│ Wires stages together. Owns the run lifecycle. │
└────────────────────────┬────────────────────────────────┘
│
┌─────────────────────┼─────────────────────┐
▼ ▼ ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ INGESTION │ │ VALIDATION │ │ TRANSFORM │
│ shopify.py │ │ schemas.py │ │ shopify_.py │
│ meta_ads.py │ │ header_map │ │ meta_.py │
│ │ │ validators │ │ cleaning.py │
└──────────────┘ └──────────────┘ └──────────────┘
│
▼
┌─────────────────────────────────────────────────────────┐
│ STORAGE + MODELING │
│ database/duckdb_engine.py ← load, read, execute │
│ sql/*.sql ← business logic │
└────────────────────────┬────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────┐
│ PRESENTATION HELPERS │
│ reporting/dashboard_data.py ← queries the model │
│ reporting/kpi_ribbon.py ← period aggregates │
│ reporting/roas.py ← category classification│
│ reporting/export.py ← CSV serialization │
└─────────────────────────────────────────────────────────┘

**Dependency rule:** arrows point downward. Nothing in `src/` imports
Streamlit. Nothing in `src/database` or `src/transformation` imports
Streamlit or CLI helpers.

## Data flow

1. **Ingest:** `read_*_csv` reads the raw file as a string-typed pandas
   DataFrame. No type coercion.
2. **Map headers:** `map_headers` normalizes raw column names to canonical
   names. Fatal on missing required columns.
3. **Validate rows:** `validate_required_values` rejects rows with missing
   required fields. Deduplicates on `order_id` for Shopify.
4. **Transform:** source-specific modules parse dates, money, and statuses.
   They reject rows with unparseable values, filter to revenue-recognized
   orders (Shopify) or single-day intervals (Meta), and convert currency.
5. **Load:** cleaned rows are written to DuckDB as tables
   (`shopify_orders_clean`, `meta_ads_clean`) via `CREATE OR REPLACE TABLE`.
6. **Model:** SQL files in `sql/` are executed in numeric order. They build
   the daily aggregates and the final `daily_financial_model`.
7. **Read:** the CLI prints a summary from `daily_financial_model`. The
   dashboard reads it via `load_model`. CSV export serializes it.

## Why SQL for the modeling layer

The financial logic lives in `sql/`, not in pandas, for three reasons:

1. **Auditability.** A CFO or analyst can read the SQL and verify the
   arithmetic. A chain of pandas operations is opaque to non-Python
   stakeholders.
2. **Correctness at scale.** Joins, aggregations, and windowing are what
   columnar databases are built for. DuckDB runs them faster than pandas
   and with less memory.
3. **Diffability.** A `.sql` file changes cleanly in git. A refactored
   pandas pipeline produces diffs that look nothing like the semantic
   change.

## The date spine

The model uses a **date spine** rather than a `FULL OUTER JOIN` between
Shopify and Meta aggregates.

shopify_daily ───┐
├──► date_spine ──► daily_financial_model
meta_daily ──────┘


The spine is `generate_series(min_date, max_date, INTERVAL 1 DAY)` over
the union of both sources' ranges. Both daily aggregates are
`LEFT JOIN`-ed onto it. Days with data in neither source appear with zeros
in money columns and NULL in nullable columns.

**Why not FULL OUTER JOIN?** A FULL OUTER JOIN of the two aggregates only
includes dates present in at least one. A quiet weekend with no orders and
no ad spend would disappear from the model. The date spine guarantees a
continuous time series.

## The materialized model

`daily_financial_model` is a **table**, not a view. This matters:

- The SQL for the model uses `getvariable('cogs_percentage')`, a session
  variable set by the pipeline at run time.
- Views are evaluated lazily. A fresh connection reading a view that
  depends on a session variable would see NULL.
- Materializing as a table freezes the values at run time. Any subsequent
  reader sees consistent numbers.

To refresh the model, re-run the pipeline. There is no partial refresh.

## Adding a new source

To add a new data source (e.g., Google Ads):

1. Add `ColumnSpec` entries to `src/validation/schemas.py`.
2. Add a `read_*_csv` and `ingest_*` module under `src/ingestion/`.
3. Add a `transform_*` module under `src/transformation/`.
4. Add a `sql/0X_*_daily.sql` file that aggregates to daily grain.
5. Add a new CTE to `sql/04_daily_financial_model.sql` that LEFT JOINs
   the new daily aggregate onto the date spine.
6. Add tests following the pattern of `tests/test_meta_transform.py`.

## Adding a new KPI

If the KPI is a per-day value:

1. Add the formula to `sql/04_daily_financial_model.sql` as a new column.
2. Add it to `DASHBOARD_COLUMNS` in `src/reporting/dashboard_data.py` if
   the dashboard should display it.
3. Add an assertion to `tests/test_golden_dataset.py` with the
   hand-calculated value.

If the KPI is a period aggregate (like the ribbon):

1. Add it to `RibbonKPIs` in `src/reporting/kpi_ribbon.py`.
2. Add a test to `tests/test_kpi_ribbon.py`.

## Error hierarchy

PipelineError
├── ConfigurationError
├── SchemaError (fatal; pipeline stops)
├── DataQualityError (fatal; too many rows rejected)
├── TransformationError
├── CurrencyError
└── DatabaseError


The CLI maps each subclass to a distinct exit code. Streamlit catches
`PipelineError` and shows a friendly message.

## Configuration

All configuration is in `config/settings.py`. It's a pydantic
`BaseSettings` subclass, so:

- Environment variables override defaults.
- `.env` overrides defaults.
- Explicit constructor arguments override everything.

Nothing else in the codebase reads `os.environ`. The `settings` singleton
is the single source of truth.