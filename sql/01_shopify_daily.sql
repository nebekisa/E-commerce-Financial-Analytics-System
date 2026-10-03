-- Aggregate cleaned Shopify orders to daily grain.
--
-- Input:  shopify_orders_clean (one row per order, monetary columns already
--         converted to the reporting currency)
-- Output: shopify_daily (one row per calendar_date)
--
-- Notes:
--   * "orders" counts DISTINCT order_id, not row count. If a future transform
--     emits multiple rows per order (e.g., per line item), the count remains
--     correct.
--   * Monetary columns are summed.
--   * avg_discount is computed as discount_amount / orders, guarded against
--     division by zero. If orders = 0 the column is NULL, not NaN or 0.

CREATE OR REPLACE VIEW shopify_daily AS
SELECT
    calendar_date,
    SUM(gross_amount)                AS gross_revenue,
    SUM(discount_amount)             AS discount_amount,
    SUM(net_amount)                  AS net_revenue,
    SUM(taxes)                       AS taxes,
    SUM(shipping_fees)               AS shipping_fees,
    COUNT(DISTINCT order_id)         AS orders,
    CASE
        WHEN COUNT(DISTINCT order_id) > 0
        THEN SUM(discount_amount) / COUNT(DISTINCT order_id)
        ELSE NULL
    END                              AS avg_discount_per_order,
    MAX(reporting_currency)          AS reporting_currency
FROM shopify_orders_clean
GROUP BY calendar_date
;