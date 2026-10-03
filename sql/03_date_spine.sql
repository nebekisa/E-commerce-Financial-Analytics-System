-- Generate a continuous date spine covering the union of both sources' ranges.
--
-- Purpose: ensures the daily_financial_model has one row per calendar date,
-- even on days with no orders and no ad spend. This is required for a
-- continuous time series in the dashboard.
--
-- Approach: rather than a FULL OUTER JOIN of shopify_daily and meta_daily
-- (which would miss dates absent from BOTH sources), we generate a complete
-- range and LEFT JOIN both aggregates onto it. This is strictly more robust
-- and produces the same result when there are no gaps.
--
-- Type note: DuckDB's generate_series only accepts (TIMESTAMP, TIMESTAMP,
-- INTERVAL), not (DATE, DATE, INTERVAL). We cast the bounds to TIMESTAMP and
-- cast the result back to DATE. The bounds come from MIN/MAX of DATE columns
-- in the input tables.

CREATE OR REPLACE VIEW date_spine AS
WITH bounds AS (
    SELECT
        MIN(d) AS min_d,
        MAX(d) AS max_d
    FROM (
        SELECT MIN(calendar_date) AS d FROM shopify_daily
        UNION ALL
        SELECT MIN(calendar_date) AS d FROM meta_daily
        UNION ALL
        SELECT MAX(calendar_date) AS d FROM shopify_daily
        UNION ALL
        SELECT MAX(calendar_date) AS d FROM meta_daily
    ) x
    WHERE d IS NOT NULL
)
SELECT
    CAST(gs AS DATE) AS calendar_date
FROM bounds,
     UNNEST(generate_series(
         CAST(min_d AS TIMESTAMP),
         CAST(max_d AS TIMESTAMP),
         INTERVAL 1 DAY
     )) AS t(gs)
ORDER BY calendar_date
;