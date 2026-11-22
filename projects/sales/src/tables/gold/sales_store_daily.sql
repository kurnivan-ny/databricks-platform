-- Additive measures per store and business day.
--   net sales = gross sales - discounts - returns (excl. VAT)
--   COGS      = cost of units sold - cost of units returned
--   transactions / units count SALE receipts only
WITH line_totals AS (
  SELECT
    store_id,
    business_date,
    SUM(CASE WHEN txn_type = 'SALE' THEN gross_amount ELSE 0 END) AS gross_sales,
    SUM(CASE WHEN txn_type = 'SALE' THEN discount_amount ELSE 0 END) AS discounts,
    SUM(CASE WHEN txn_type = 'RETURN' THEN net_amount ELSE 0 END) AS returns,
    SUM(CASE WHEN txn_type = 'SALE' THEN cost_amount ELSE -cost_amount END) AS cogs,
    SUM(CASE WHEN txn_type = 'SALE' THEN quantity ELSE 0 END) AS units_sold,
    SUM(CASE WHEN txn_type = 'RETURN' THEN quantity ELSE 0 END) AS units_returned,
    COUNT(DISTINCT CASE WHEN txn_type = 'SALE' THEN txn_id END) AS transactions,
    COUNT(DISTINCT CASE WHEN txn_type = 'RETURN' THEN txn_id END) AS return_transactions
  FROM ${catalog}.${silver_schema}.sales_transaction_lines
  GROUP BY store_id, business_date
),
store_days AS (
  SELECT store_id, business_date FROM line_totals
  UNION
  SELECT store_id, business_date FROM ${catalog}.${silver_schema}.sales_store_traffic
)
SELECT
  d.store_id,
  d.business_date,
  CAST(DATE_TRUNC('MONTH', d.business_date) AS DATE) AS month,
  s.store_name,
  s.region,
  s.city,
  s.selling_area_m2,
  s.open_date,
  COALESCE(l.gross_sales, 0) AS gross_sales,
  COALESCE(l.discounts, 0) AS discounts,
  COALESCE(l.returns, 0) AS returns,
  COALESCE(l.gross_sales, 0) - COALESCE(l.discounts, 0) - COALESCE(l.returns, 0) AS net_sales,
  COALESCE(l.cogs, 0) AS cogs,
  COALESCE(l.units_sold, 0) AS units_sold,
  COALESCE(l.units_returned, 0) AS units_returned,
  COALESCE(l.transactions, 0) AS transactions,
  COALESCE(l.return_transactions, 0) AS return_transactions,
  COALESCE(t.visitors, 0) AS traffic
FROM store_days AS d
JOIN ${catalog}.${silver_schema}.sales_stores AS s
  ON s.store_id = d.store_id
LEFT JOIN line_totals AS l
  ON l.store_id = d.store_id AND l.business_date = d.business_date
LEFT JOIN ${catalog}.${silver_schema}.sales_store_traffic AS t
  ON t.store_id = d.store_id AND t.business_date = d.business_date
