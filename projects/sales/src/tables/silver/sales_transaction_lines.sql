-- Flatten receipts into one row per line and derive line amounts.
-- Amounts are positive for both SALE and RETURN lines; txn_type distinguishes them.
SELECT
  r.txn_id,
  r.store_id,
  r.business_date,
  r.txn_ts,
  r.txn_type,
  r.original_txn_id,
  line.line_no AS line_no,
  line.product_id AS product_id,
  line.quantity AS quantity,
  line.unit_price AS unit_price,
  CAST(line.quantity * line.unit_price AS DECIMAL(12, 2)) AS gross_amount,
  line.discount_amount AS discount_amount,
  CAST(line.quantity * line.unit_price - line.discount_amount AS DECIMAL(12, 2)) AS net_amount,
  CAST(line.quantity * line.unit_cost AS DECIMAL(12, 2)) AS cost_amount
FROM ${catalog}.${bronze_schema}.sales_transactions_raw AS r
LATERAL VIEW explode(r.lines) exploded AS line
