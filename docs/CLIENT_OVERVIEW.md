# Financial Analytics — Overview

A one-page summary of what this system does, what it needs from you, and
what we still need to confirm before we can trust the numbers.

---

## What it replaces

Every weekend, four hours of manual work:

1. Download the Shopify order export.
2. Download the Meta Ads export.
3. Clean both files in Excel.
4. Match the dates.
5. Calculate revenue, ad spend, and margin.
6. Build the charts.
7. Send the report.

The system does all of that in about ten seconds. You upload the two
files, click a button, and get a dashboard. The numbers are the same
ones you'd have calculated by hand — but consistently, every time, with
no copy-paste errors.

---

## What it produces

A daily financial table with, for each date:

- **Revenue:** gross, net, discounts, taxes, shipping fees
- **Orders:** count of paid orders
- **Ad spend:** Meta spend, converted to your reporting currency
- **Estimated contribution margin:** net revenue minus ad spend minus
  estimated cost of goods
- **Blended ROAS:** how many ETB of revenue you got per ETB of ad spend
- **Profit margin:** the fraction of net revenue that became contribution
  margin

You can view this as a dashboard or download it as a spreadsheet.

---

## What you need to provide

**Two files, once per reporting period (usually weekly):**

1. **Shopify export** — the standard order export from your Shopify admin.
2. **Meta Ads export** — from Meta Ads Manager. Must be **daily
   granularity** (each row covers one day). If you export at a summary
   level, the system will reject the file and tell you to re-export.

**One piece of information to set up, once:**

- The current USD-to-ETB exchange rate.

Everything else is configured.

---

## What's confirmed and what needs confirming

We built the system based on standard Shopify and Meta conventions. Before
we hand it over and you start using the numbers, **we need to confirm
four things against a real sample of your exports.** Each one affects the
accuracy of the output.

### 1. What "Net Amount" means in your Shopify export

Shopify's export labels are not perfectly consistent. We assume:

- **Gross Amount** = order subtotal before discounts and taxes.
- **Net Amount** = gross minus discounts, excluding taxes and shipping.

If your export defines these differently — for example, if "Net Amount"
includes taxes or shipping — your revenue numbers will be off by
**15–25%**.

**What we need:** one Shopify export (anonymized if you prefer) with a
handful of orders. We'll compare the values against your Shopify admin
to confirm the interpretation.

### 2. How refunds appear in your export

Two possibilities:

- **(a)** Refunds are separate rows with negative amounts. In this case
  we need to net them against the refund date.
- **(b)** Refunded orders keep their original row but change status. In
  this case we handle them via the "Financial Status" column.

We currently assume **(b)**. If your export uses **(a)**, refunds are
being ignored and revenue is overstated.

**What we need:** the same sample export. If it contains a refund, we can
tell which case applies.

### 3. Your Meta ad account timezone

Meta reports ad spend by day in the timezone of the **ad account**, not
your local timezone. We assume the ad account is set to Addis Ababa time
(UTC+3), matching your business calendar.

If the ad account is set to a different timezone — for example, US Pacific
— then "Monday" in the Meta data is not the same "Monday" as in your
Shopify orders. Daily ROAS will be off by up to 24 hours, and the
"worst day" might actually be an artifact of the mismatch.

**What we need:** you to check the timezone in Meta Business Settings and
confirm it matches your business timezone. If it doesn't, changing it in
Meta is a one-time setting and the fix is trivial.

### 4. The exchange rate

Your Shopify revenue is in ETB. Your Meta ad spend is in USD. To compare
them, we convert at a fixed rate — currently **1 USD = 130 ETB**.

That rate is a snapshot. It doesn't update automatically. If the actual
rate moves significantly, all the USD-derived numbers in the report will
be off by the difference.

**What we need:** you to tell us which rate you want to use. Options:

- **Fixed annual rate** (simple, consistent across the year).
- **Weekly rate**, updated manually each reporting period.
- **Live rate** from an API (a future enhancement; not built yet).

For now, the rate lives in a configuration file. When it changes, you
change it there and re-run the pipeline.

---

## What it does not do

Being honest about scope is more valuable than a longer feature list.

- **No SKU-level cost of goods.** Cost is estimated as 40% of gross
  revenue, flat across all products. If your margins vary widely by
  product, this estimate will be wrong on individual products, though it
  may average out over a period.
- **No attribution.** We report blended ROAS — total revenue per total
  ad spend. We do not say "Campaign X drove Y sales."
- **No real-time data.** The system runs when you run it. There's no live
  feed from Shopify or Meta.
- **No multiple currencies per Shopify order.** If you ever sell in a
  currency other than ETB, those orders need to be handled separately.
- **No historical backfill beyond what you provide.** The system reads
  the files you give it. If you want 12 months of history, you provide
  12 months of exports.
- **No authentication on the dashboard.** It runs on your machine and is
  not exposed to the internet. If it's ever deployed on a shared
  network, we need to add access control first.

---

## What comes next

**Step 1 — Assumption confirmation.** You provide one or two sample
exports. We compare them against what the system expects and adjust
where needed. This is a 1–2 hour exercise and it's the single most
important step before we trust the numbers.

**Step 2 — Kickoff.** We walk through the dashboard together with real
data. You ask questions. We note anything that needs to change.

**Step 3 — Adoption.** You start using it. We're available for the first
two reporting cycles to fix anything that comes up.

**Step 4 — Optional enhancements.** Depending on how things go:

- Live FX rate from an API.
- SKU-level cost data.
- Scheduled runs (the pipeline runs itself weekly and emails the report).
- Slack or email alerts when a KPI crosses a threshold.

These are not built yet. They're the kinds of features that make sense
once the core system is in daily use.

---

## Where the numbers come from

Every number in the dashboard traces back to a source column and a
formula. Nothing is derived from a black box. If you ever want to know
"why is September 3 showing X?", we can point to the exact orders and
the exact ad spend that produced it.

That auditability is deliberate. Financial numbers need to be
explainable, not just plausible.