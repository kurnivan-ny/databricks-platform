-- Base measures per store and month (source of the sales_store_metrics metric view).
--   is_comparable : store has traded >= 12 full months before the month
--   *_py          : same store, same calendar days one year earlier (like-for-like, so the
--                   current partial month is compared with the same days last year)
WITH monthly AS (
  SELECT
    store_id,
    month,
    store_name,
    region,
    city,
    selling_area_m2,
    open_date,
    MAX(business_date) AS last_business_date,
    COUNT(*) AS trading_days,
    SUM(gross_sales) AS gross_sales,
    SUM(discounts) AS discounts,
    SUM(returns) AS returns,
    SUM(net_sales) AS net_sales,
    SUM(cogs) AS cogs,
    SUM(units_sold) AS units_sold,
    SUM(units_returned) AS units_returned,
    SUM(transactions) AS transactions,
    SUM(return_transactions) AS return_transactions,
    SUM(traffic) AS traffic
  FROM ${catalog}.${gold_schema}.sales_store_daily
  GROUP BY store_id, month, store_name, region, city, selling_area_m2, open_date
),
flagged AS (
  SELECT
    *,
    CASE
      WHEN DAY(open_date) = 1 THEN CAST(DATE_TRUNC('MONTH', open_date) AS DATE)
      ELSE ADD_MONTHS(CAST(DATE_TRUNC('MONTH', open_date) AS DATE), 1)
    END AS first_full_month
  FROM monthly
),
prior_year AS (
  SELECT
    m.store_id,
    m.month,
    SUM(d.gross_sales) AS gross_sales_py,
    SUM(d.discounts) AS discounts_py,
    SUM(d.returns) AS returns_py,
    SUM(d.net_sales) AS net_sales_py,
    SUM(d.cogs) AS cogs_py,
    SUM(d.units_sold) AS units_sold_py,
    SUM(d.transactions) AS transactions_py,
    SUM(d.traffic) AS traffic_py
  FROM monthly AS m
  JOIN ${catalog}.${gold_schema}.sales_store_daily AS d
    ON d.store_id = m.store_id
   AND d.business_date BETWEEN ADD_MONTHS(m.month, -12) AND ADD_MONTHS(m.last_business_date, -12)
  GROUP BY m.store_id, m.month
)
SELECT
  f.*,
  ADD_MONTHS(f.first_full_month, 12) <= f.month AS is_comparable,
  CASE WHEN p.store_id IS NOT NULL THEN f.selling_area_m2 END AS selling_area_m2_py,
  p.gross_sales_py,
  p.discounts_py,
  p.returns_py,
  p.net_sales_py,
  p.cogs_py,
  p.units_sold_py,
  p.transactions_py,
  p.traffic_py
FROM flagged AS f
LEFT JOIN prior_year AS p
  ON p.store_id = f.store_id AND p.month = f.month
