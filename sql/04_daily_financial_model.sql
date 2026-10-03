-- The unified daily financial model.
--
-- Joins shopify_daily, meta_daily, and the date spine, then computes KPIs.
--
-- Inputs: shopify_daily, meta_daily, date_spine
-- Output: daily_financial_model (one row per date in the union range)
--
-- Design note: this is a TABLE, not a VIEW.
-- The COGS-dependent columns (cogs_estimate, contribution_margin,
-- profit_margin) are computed using a session variable `cogs_percentage`
-- that the pipeline sets at runtime. If this were a VIEW, any reader
-- opening a fresh connection would see those columns evaluate to NULL
-- because the session variable is not set. Materializing as a table
-- freezes the correct values at pipeline run time and makes the model
-- readable by any downstream consumer without needing session state.
--
-- To refresh the model after changing cogs_percentage or source data,
-- re-run the pipeline.

CREATE OR REPLACE TABLE daily_financial_model AS
WITH joined AS (
    SELECT
        ds.calendar_date,

        COALESCE(sd.gross_revenue,   0.0) AS gross_revenue,
        COALESCE(sd.discount_amount, 0.0) AS discount_amount,
        COALESCE(sd.net_revenue,     0.0) AS net_revenue,
        COALESCE(sd.taxes,           0.0) AS taxes,
        COALESCE(sd.shipping_fees,   0.0) AS shipping_fees,
        COALESCE(sd.orders,          0)   AS orders,

        COALESCE(md.ad_spend,        0.0) AS ad_spend,
        md.impressions                    AS impressions,
        md.link_clicks                    AS link_clicks,

        COALESCE(sd.reporting_currency, md.reporting_currency)::VARCHAR AS reporting_currency
    FROM date_spine ds
    LEFT JOIN shopify_daily sd USING (calendar_date)
    LEFT JOIN meta_daily md    USING (calendar_date)
)
SELECT
    calendar_date,
    gross_revenue,
    discount_amount,
    net_revenue,
    taxes,
    shipping_fees,
    orders,
    ad_spend,
    impressions,
    link_clicks,

    (gross_revenue * CAST(getvariable('cogs_percentage') AS DOUBLE)) AS cogs_estimate,

    (
        net_revenue
        - ad_spend
        - gross_revenue * CAST(getvariable('cogs_percentage') AS DOUBLE)
    ) AS contribution_margin,

    CASE
        WHEN ad_spend > 0 THEN net_revenue / ad_spend
        ELSE NULL
    END AS roas,

    CASE
        WHEN net_revenue > 0 THEN ad_spend / net_revenue
        ELSE NULL
    END AS mer,

    CASE
        WHEN net_revenue > 0
        THEN (
            net_revenue
            - ad_spend
            - gross_revenue * CAST(getvariable('cogs_percentage') AS DOUBLE)
        ) / net_revenue
        ELSE NULL
    END AS profit_margin,

    reporting_currency
FROM joined
ORDER BY calendar_date
;