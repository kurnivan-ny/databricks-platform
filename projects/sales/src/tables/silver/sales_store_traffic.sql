-- Daily visitors per store from the door counters.
SELECT
  store_id,
  business_date,
  visitors
FROM ${catalog}.${bronze_schema}.sales_store_traffic_raw
