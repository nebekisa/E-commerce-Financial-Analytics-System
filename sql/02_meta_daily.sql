-- Aggregate cleaned Meta Ads rows to daily grain.
--
-- Input:  meta_ads_clean (one row per campaign-day, spend already in reporting
--         currency, multi-day intervals already rejected upstream)
-- Output: meta_daily (one row per calendar_date)
--
-- Notes:
--   * impressions and link_clicks are NULLABLE. SUM ignores NULLs; if every
--     row for a date has NULL, the result is NULL. That's intentional: "no
--     data" is different from "zero."
--   * We do NOT aggregate by campaign here. The daily model is per-date.
--     Campaign-level views are a Phase 12 extension.

CREATE OR REPLACE VIEW meta_daily AS
SELECT
    calendar_date,
    SUM(spend_amount)                AS ad_spend,
    SUM(impressions)                 AS impressions,
    SUM(link_clicks)                 AS link_clicks,
    COUNT(*)                         AS meta_row_count,
    MAX(reporting_currency)          AS reporting_currency
FROM meta_ads_clean
GROUP BY calendar_date
;