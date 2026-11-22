-- One row per product (master-data file is a full snapshot).
SELECT
  product_id,
  product_name,
  category,
  unit_price,
  unit_cost
FROM ${catalog}.${bronze_schema}.sales_products_raw
