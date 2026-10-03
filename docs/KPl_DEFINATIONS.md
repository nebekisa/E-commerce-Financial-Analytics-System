# KPI Definitions

Every KPI in the system, its formula, its guards, and the business
interpretation.

## Revenue

### gross_revenue

Sum of `gross_amount` across recognized Shopify orders on the given date.

**Interpretation:** pre-discount, pre-tax, pre-shipping line-item subtotal.
This is the "top line" before any deductions.

### discount_amount

Sum of `discount_amount` across recognized orders.

### net_revenue

Sum of `net_amount` across recognized orders.

**Assumption:** `net_amount = gross_amount − discount_amount`, tax-exclusive,
shipping-exclusive. **This must be confirmed against a real Shopify export.**
If the client's export defines `net_amount` as post-tax or including
shipping, this KPI is wrong by 15–25%.

### orders

Count of distinct `order_id` values with a revenue-recognized financial
status.

**Recognized statuses** (configurable): `paid`, `partially_paid`,
`partially_refunded`.

**Excluded statuses:** `pending`, `cancelled`, `refunded`, `voided`.

Unknown statuses are excluded with a warning logged.

## Advertising

### ad_spend

Sum of Meta ad spend on the given date, converted to the reporting currency.

**Conversion:** `spend_amount × usd_to_reporting_fx_rate`. The rate is a
static configuration value. It is **not** fetched from an API.

### impressions

Sum of Meta impressions for the date. **Nullable.** A day with no Meta
data has NULL impressions, not zero. This distinction matters: "we don't
have the data" is not the same as "the campaign had zero impressions."

### link_clicks

Sum of Meta link clicks. Same nullability semantics as impressions.

## Ratios

### Blended ROAS
blended_roas = net_revenue / ad_spend

**Guard:** NULL when `ad_spend = 0`.

**Interpretation:** "For every 1 unit of reporting currency spent on Meta,
we recognized X units of net product revenue." This is a revenue ratio,
not a profit ratio. A ROAS of 4 with 40% COGS can still be unprofitable if
ad spend is high enough.

**"Blended"** means period-aggregated, not per-campaign. We do not compute
per-campaign ROAS. If the client needs that, it's a Phase 12 extension.

### Meta Spend / Net Revenue (labelled "MER" in the model column)

meta_spend_ratio = ad_spend / net_revenue


**Guard:** NULL when `net_revenue = 0`.

**This is NOT the industry-standard Marketing Efficiency Ratio.** The
standard MER is `Total Revenue / Total Marketing Spend` and includes all
channels, not just Meta. The client requested `ad_spend / net_revenue`,
so we implement that, but we label it clearly in the dashboard as
"Meta Spend / Net Revenue".

**The model column is named `mer` for backward compatibility with the
client's requested schema. This is misleading and will be renamed in a
future version.**

### Estimated Contribution Margin

contribution_margin = net_revenue − ad_spend − cogs_estimate

where
cogs_estimate = cogs_percentage × gross_revenue


**Interpretation:** an estimate of the contribution each day makes toward
fixed costs. It is **not** true contribution margin because:

- COGS is a flat percentage, not actual cost.
- Only Meta ad spend is included, not other marketing.
- Fulfillment, payment processing, and returns are excluded.

The dashboard labels this "Estimated Contribution Margin" with a tooltip
explaining what's excluded.

### Profit Margin

profit_margin = contribution_margin / net_revenue

**Guard:** NULL when `net_revenue = 0`.

**Interpretation:** fraction of net revenue that becomes estimated
contribution. Negative values mean the day lost money on a contribution
basis.

## Administrative hours saved

hours_saved = admin_hours_per_week × (days_in_range / 7)


Rounded to 1 decimal.

**Interpretation:** an estimate of the manual work replaced by the
pipeline, based on the client's baseline of 4 hours per weekend. Not a
KPI in any financial sense; a storytelling metric for the "why does this
system exist" conversation.

## Report-level KPIs

The CLI summary and dashboard ribbon compute the same KPIs, but aggregated
over the full selected range:

- Total net revenue = SUM of daily net_revenue
- Total ad spend = SUM of daily ad_spend
- Total contribution margin = SUM of daily contribution_margin
- Blended ROAS = total net revenue / total ad spend (not average of daily)
- Meta spend ratio = total ad spend / total net revenue
- Profit margin = total contribution margin / total net revenue

**Important:** the period ROAS is not the average of daily ROAS. It's the
ratio of the sums, which weights high-spend days more heavily. This is the
correct interpretation.

## Why the guards matter

Every division in the model uses `CASE WHEN denominator > 0 THEN ... ELSE
NULL`. This is deliberate:

- **Division by zero in SQL returns NULL by default in some engines and
  raises in others.** Explicit guards make the behavior portable and clear.
- **A missing ratio is not the same as zero.** A day with no ad spend has
  *undefined* ROAS, not ROAS = 0. The dashboard shows "—" for undefined,
  not "0.00".
- **NULL propagates correctly through SUM and AVG.** If we substituted 0
  for NULL, the period aggregate would be wrong.