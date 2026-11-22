# sales project

Retail sales and store-performance analytics on synthetic POS and door-counter data.

* **Bundle:** `sales`, with targets `dev` (catalog `dev`, folder
  `/Workspace/databricks-platform/dev/sales`) and `prod` (catalog `prod`, folder
  `/Workspace/databricks-platform/prod/sales`).
* **Job `[<target>] sales_daily`:** serverless, daily at 06:00 UTC, paused in dev. It runs
  these tasks in order:
  1. `generate_data`
  2. `build_bronze`
  3. `build_silver`
  4. `build_gold`
  5. `publish_metric_views`
  6. `quality_checks`
* **Dashboard `[<target>] Sales & Store Performance`:** two pages, *Sales* and *Store
  performance*, built on the metric views.

| Layer | Tables | Write mode |
|---|---|---|
| bronze | `sales_transactions_raw`, `sales_store_traffic_raw` | append new landing files |
| bronze | `sales_stores_raw`, `sales_products_raw` | replace (master-data snapshots) |
| silver | `sales_stores`, `sales_products`, `sales_transaction_lines`, `sales_store_traffic` | merge on keys (+ `*_quarantine`) |
| gold | `sales_store_daily`, `sales_store_monthly`, `sales_category_monthly` | replace |
| gold | metric views `sales_store_metrics`, `sales_category_metrics` | `CREATE OR REPLACE VIEW … WITH METRICS` |

KPI formulas: [../../docs/kpi-definitions.md](../../docs/kpi-definitions.md).

Run the tests with `pytest projects/sales` from the repo root.
