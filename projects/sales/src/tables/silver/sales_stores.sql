-- One row per store (latest master-data file wins; file is a full snapshot).
SELECT
  store_id,
  store_name,
  region,
  city,
  selling_area_m2,
  open_date
FROM ${catalog}.${bronze_schema}.sales_stores_raw
