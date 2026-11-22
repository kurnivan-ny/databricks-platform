"""Verify the deployed dashboards of a bundle target actually work.

For every dashboard in ``databricks bundle summary``, fetch the *deployed* definition and
run each widget's query on the dashboard's SQL warehouse. Widget fields over metric-view
datasets (e.g. ``MEASURE(`atv`)``) are executed as
``SELECT <fields> FROM <metric view> GROUP BY ALL``, so a renamed or broken measure, a
wrong catalog, or a missing table fails the deployment instead of the dashboard.

Usage: python scripts/verify_dashboards.py --project-dir projects/sales --target dev
Requires the Databricks CLI on PATH and authentication via env vars or a profile.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

POLL_SECONDS, TIMEOUT_SECONDS = 3, 300


def cli(*args: str, cwd: Path | None = None) -> Any:
    result = subprocess.run(
        ["databricks", *args, "-o", "json"], cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"databricks {' '.join(args)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout or "{}")


def widget_statements(dashboard: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (label, SQL) for every widget query in a serialized dashboard."""
    datasets = {d["name"]: d for d in dashboard.get("datasets", [])}
    statements = []
    for page in dashboard.get("pages", []):
        for item in page.get("layout", []):
            widget = item.get("widget", {})
            for q in widget.get("queries", []):
                spec = q.get("query", {})
                dataset = datasets.get(spec.get("datasetName"))
                if dataset is None:
                    raise ValueError(f"widget {widget.get('name')!r}: unknown dataset")
                fields = spec.get("fields") or []
                select = ", ".join(f"{f['expression']} AS `{f['name']}`" for f in fields) or "1"
                if "asset_name" in dataset:
                    source = dataset["asset_name"]
                else:
                    source = "(" + "".join(dataset.get("queryLines", [])) + ") AS q"
                group = "" if spec.get("disaggregated") else " GROUP BY ALL"
                label = f"{page.get('name')}/{widget.get('name')}/{q.get('name')}"
                statements.append((label, f"SELECT {select} FROM {source}{group} LIMIT 10"))
    return statements


def run_statement(sql: str, warehouse_id: str, catalog: str | None, schema: str | None) -> int:
    body: dict[str, Any] = {"statement": sql, "warehouse_id": warehouse_id, "wait_timeout": "30s"}
    if catalog:
        body["catalog"] = catalog
    if schema:
        body["schema"] = schema
    response = cli("api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while response.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        if time.monotonic() > deadline:
            raise TimeoutError("statement did not finish in time")
        time.sleep(POLL_SECONDS)
        response = cli("api", "get", f"/api/2.0/sql/statements/{response['statement_id']}")
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(status.get("error", {}).get("message", status))
    return int(response.get("manifest", {}).get("total_row_count", 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)

    summary = cli("bundle", "summary", "-t", args.target, cwd=args.project_dir)
    dashboards = (summary.get("resources") or {}).get("dashboards") or {}
    if not dashboards:
        print("no dashboards in bundle; nothing to verify")
        return 0

    failures = 0
    for key, resource in dashboards.items():
        dashboard_id = resource.get("id")
        if not dashboard_id:
            print(f"[FAIL] {key}: not deployed (no id in bundle summary)")
            failures += 1
            continue
        deployed = cli("lakeview", "get", dashboard_id)
        definition = json.loads(deployed.get("serialized_dashboard") or "{}")
        warehouse = resource.get("warehouse_id") or deployed.get("warehouse_id")
        for label, sql in widget_statements(definition):
            try:
                rows = run_statement(
                    sql, warehouse, resource.get("dataset_catalog"), resource.get("dataset_schema")
                )
                if rows == 0:
                    raise RuntimeError("query returned no rows")
                print(f"[PASS] {key}: {label} ({rows} rows)")
            except Exception as exc:
                failures += 1
                print(f"[FAIL] {key}: {label}: {exc}\n       SQL: {sql}")
    print(f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
