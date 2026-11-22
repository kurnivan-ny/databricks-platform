-- Base measures per store, product category and month (source of the
-- sales_category_metrics metric view). Prior-year values reuse the store-month
-- like-for-like window so category and store figures always cover the same days.
WITH daily AS (
  SELECT
    l.store_id,
    l.business_date,
    p.category,
    SUM(CASE WHEN l.txn_type = 'SALE' THEN l.gross_amount ELSE 0 END) AS gross_sales,
    SUM(CASE WHEN l.txn_type = 'SALE' THEN l.discount_amount ELSE 0 END) AS discounts,
    SUM(CASE WHEN l.txn_type = 'RETURN' THEN l.net_amount ELSE 0 END) AS returns,
    SUM(CASE WHEN l.txn_type = 'SALE' THEN l.cost_amount ELSE -l.cost_amount END) AS cogs,
    SUM(CASE WHEN l.txn_type = 'SALE' THEN l.quantity ELSE 0 END) AS units_sold
  FROM ${catalog}.${silver_schema}.sales_transaction_lines AS l
  JOIN ${catalog}.${silver_schema}.sales_products AS p
    ON p.product_id = l.product_id
  GROUP BY l.store_id, l.business_date, p.category
),
monthly AS (
  SELECT
    store_id,
    CAST(DATE_TRUNC('MONTH', business_date) AS DATE) AS month,
    category,
    SUM(gross_sales) AS gross_sales,
    SUM(discounts) AS discounts,
    SUM(returns) AS returns,
    SUM(gross_sales) - SUM(discounts) - SUM(returns) AS net_sales,
    SUM(cogs) AS cogs,
    SUM(units_sold) AS units_sold
  FROM daily
  GROUP BY store_id, CAST(DATE_TRUNC('MONTH', business_date) AS DATE), category
),
prior_year AS (
  SELECT
    m.store_id,
    m.month,
    m.category,
    SUM(d.gross_sales) - SUM(d.discounts) - SUM(d.returns) AS net_sales_py,
    SUM(d.cogs) AS cogs_py,
    SUM(d.units_sold) AS units_sold_py
  FROM monthly AS m
  JOIN ${catalog}.${gold_schema}.sales_store_monthly AS sm
    ON sm.store_id = m.store_id AND sm.month = m.month
  JOIN daily AS d
    ON d.store_id = m.store_id
   AND d.category = m.category
   AND d.business_date BETWEEN ADD_MONTHS(m.month, -12) AND ADD_MONTHS(sm.last_business_date, -12)
  GROUP BY m.store_id, m.month, m.category
)
SELECT
  m.store_id,
  m.month,
  m.category,
  s.store_name,
  s.region,
  s.city,
  m.gross_sales,
  m.discounts,
  m.returns,
  m.net_sales,
  m.cogs,
  m.units_sold,
  p.net_sales_py,
  p.cogs_py,
  p.units_sold_py
FROM monthly AS m
JOIN ${catalog}.${silver_schema}.sales_stores AS s
  ON s.store_id = m.store_id
LEFT JOIN prior_year AS p
  ON p.store_id = m.store_id AND p.month = m.month AND p.category = m.category
