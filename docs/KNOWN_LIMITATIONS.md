# Known Limitations

An honest list of what this system does not do, and why. If any of these
matters for a specific deployment, the corresponding fix is documented.

## Data and business logic

### `net_amount` semantics are assumed

We assume `net_amount = gross_amount − discount_amount`, tax-exclusive,
shipping-exclusive. This is our interpretation of the Shopify export
columns, not a confirmation. If the client's export defines `net_amount`
differently, revenue is wrong by 15–25%.

**Fix:** validate against a real Shopify export before handoff.

### Refund handling assumes no separate refund rows

We treat `refunded` and `partially_refunded` orders via their status. If
the client's export emits refunds as separate rows with negative amounts
and a distinct `order_id`, those rows are not being processed.

**Fix:** validate against a real export; if refunds are separate rows, add
a transform path.

### FX rate is static

`USD_TO_REPORTING_FX_RATE` is a configuration value. The pipeline does not
fetch a live rate. If the rate is stale, every conversion is wrong.

**Fix:** integrate a rate API; add a `fx_rate_as_of` field to config and
display it in the dashboard.

### Multi-currency Shopify orders are not supported

We assume all orders are in `shopify_source_currency`. A Shopify store can
have orders in multiple currencies. Those orders would be mis-converted.

**Fix:** reject orders whose `currency` doesn't match
`shopify_source_currency`, with a clear DQ error.

### COGS is a flat percentage

`cogs_percentage × gross_revenue` assumes a constant margin across all
products. For a store with varied margins, this is approximate.

**Fix:** maintain a SKU-level cost table and join it in the model.

### No attribution modeling

Blended ROAS is the only advertising KPI. We do not attribute revenue to
specific campaigns, ad sets, or ads.

**Fix:** join on `utm_campaign` from Shopify order landing pages, or use
the Meta Marketing API to fetch campaign-level data.

## Timezone

### Meta ad account timezone must match reporting timezone

Meta's reporting dates are in the ad account's timezone. We use them as-is.
If the ad account timezone differs from `REPORTING_TIMEZONE`, daily ad
spend is misattributed by up to 24 hours.

**Fix:** add a startup validation that warns when the ad account timezone
is not set; document the requirement for the client.

## Architecture

### No transaction boundary around the write phase

If `execute_sql_directory` fails on file 3 of 4, the database is left with
some tables updated and others not. A partial state.

**Fix:** wrap the load-and-model steps in `BEGIN TRANSACTION; ... COMMIT;`.
DuckDB supports it.

### No schema versioning

If we change `daily_financial_model` (rename a column, add a KPI), there's
no record of which version produced which output.

**Fix:** add a `pipeline_runs` table with `run_id`, `run_at`, `schema_version`.

### No incremental loading

Every run rebuilds from scratch. Fine for 100k rows; minutes for 10M.

**Fix:** partition by month, track the max loaded date per source, load
only new data.

### Single-user, single-tenant

No auth, no multi-user support, no role separation. The DuckDB file is
assumed to be on a single machine.

**Fix:** significant architecture change. Not planned.

## Testing

### No test for partial-failure database state

Related to the "no transaction boundary" item above.

### No coverage measurement

`pytest --cov` is not run. Coverage is not reported.

**Fix:** add coverage configuration and a target threshold.

## Operations

### No scheduled runs

The pipeline is invoked manually (CLI or dashboard). There is no cron,
Task Scheduler, or Airflow integration.

**Fix:** add a `pipeline_runs` table (see "no schema versioning" above),
then wire up a scheduled task. The CLI is already subprocess-safe.

### No monitoring or alerting

Logs are written to disk. Nothing watches them.

**Fix:** for a local tool, not needed. For a multi-user deployment, pipe
logs to a monitoring system.

## UX

### No "as of" timestamp on the dashboard

The client can't tell when the data was last refreshed.

**Fix:** show the `pipeline_runs.run_at` from a future `pipeline_runs` table.

### No way to inspect rejected rows

The DQ report shows counts and reasons but not the actual rows.

**Fix:** write rejected rows to `shopify_rejected` and `meta_rejected`
tables with the same schema as the accepted tables plus a
`rejection_reason` column.

### Rejection rate threshold checks only the ingestion stage

The transform stage can reject a large fraction without triggering a
threshold failure.

**Fix:** add a second `check_rejection_threshold` call after the transform.