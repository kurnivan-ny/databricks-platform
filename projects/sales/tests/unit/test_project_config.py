"""Static consistency checks across the bundle, table registry, metric views and
dashboard. These catch most deploy-time mistakes without touching a workspace."""

import json
import re
import sys

import pytest
import yaml
from platform_common.metric_views import (
    dimension_names,
    load_definitions,
    measure_names,
    validate_spec,
)
from platform_common.tables import load_registry, validate_registry
from platform_common.templating import render

VALUES = {
    "catalog": "dev",
    "bronze_schema": "bronze",
    "silver_schema": "silver",
    "gold_schema": "gold",
}
REQUESTED_KPIS = {
    "net_sales",
    "same_store_sales_growth",
    "gross_margin",
    "gross_margin_pct",
    "sales_per_m2",
    "traffic",
    "conversion_rate",
    "atv",
    "upt",
    "asp",
    "return_rate",
    "discount_rate",
}
HARDCODED_CATALOG = re.compile(r"\b(dev|prod)\.(bronze|silver|gold)\b")


@pytest.fixture(scope="module")
def bundle(request):
    path = request.path.parents[2] / "databricks.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def metric_views(request):
    directory = request.path.parents[2] / "src" / "metric_views"
    return {
        d.name: yaml.safe_load(render(d.yaml_text, VALUES)) for d in load_definitions(directory)
    }


@pytest.fixture(scope="module")
def dashboard(request):
    path = request.path.parents[2] / "dashboards" / "sales_overview.lvdash.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ bundle


def test_targets_map_to_catalogs(bundle):
    assert bundle["targets"]["dev"]["variables"]["catalog"] == "dev"
    assert bundle["targets"]["prod"]["variables"]["catalog"] == "prod"
    assert bundle["targets"]["prod"]["mode"] == "production"


def test_no_workspace_host_or_secrets_in_bundle(project_dir):
    text = "\n".join(p.read_text(encoding="utf-8") for p in project_dir.rglob("*.yml"))
    assert "host:" not in text
    assert not re.search(r"dapi[0-9a-f]{20,}", text), "personal access token committed!"


def test_job_tasks_use_known_entrypoint_commands(project_dir):
    sys.path.insert(0, str(project_dir / "src" / "jobs"))
    import entrypoint

    job = yaml.safe_load((project_dir / "resources" / "job.yml").read_text())["resources"]["jobs"][
        "sales_daily"
    ]
    for task in job["tasks"]:
        params = task["spark_python_task"]["parameters"]
        assert params[0] in entrypoint.COMMANDS, task["task_key"]
        assert any(p.startswith("--catalog=${var.catalog}") for p in params)
        args = entrypoint.parse_args([re.sub(r"\$\{[^}]+\}", "dev", p) for p in params])
        assert args.catalog == "dev"


# ------------------------------------------------------------------ table registry


def test_table_registry_is_valid(project_dir):
    registry = load_registry(project_dir / "src" / "tables" / "tables.yml")
    assert validate_registry(registry) == []


def test_registry_order_respects_dependencies(project_dir):
    registry = load_registry(project_dir / "src" / "tables" / "tables.yml")
    built: set[str] = set()
    for spec in registry.tables:
        if spec.sql:
            sql = (registry.base_dir / spec.sql).read_text(encoding="utf-8")
            for referenced in re.findall(r"\$\{\w+\}\.\$\{\w+\}\.(\w+)", sql):
                assert referenced in built, f"{spec.name} reads {referenced} before it is built"
        built.add(spec.name)


def test_sql_has_no_hardcoded_catalogs(project_dir):
    for path in (project_dir / "src").rglob("*.sql"):
        assert not HARDCODED_CATALOG.search(path.read_text(encoding="utf-8")), path


# ------------------------------------------------------------------ metric views


def test_metric_views_are_valid(metric_views):
    assert set(metric_views) == {"sales_store_metrics", "sales_category_metrics"}
    for name, spec in metric_views.items():
        assert validate_spec(spec) == [], name


def test_all_requested_kpis_and_yoy_exist(metric_views):
    measures = measure_names(metric_views["sales_store_metrics"])
    assert measures >= REQUESTED_KPIS
    for kpi in REQUESTED_KPIS - {"same_store_sales_growth"}:
        assert f"{kpi}_py" in measures, f"missing prior-year measure for {kpi}"
        assert {f"{kpi}_yoy", f"{kpi}_yoy_pts"} & measures, f"missing YoY measure for {kpi}"
    assert {"gross_margin_pct", "net_sales_yoy"} <= measure_names(
        metric_views["sales_category_metrics"]
    )


def test_metric_view_sources_are_gold_registry_tables(metric_views, project_dir):
    registry = load_registry(project_dir / "src" / "tables" / "tables.yml")
    gold = {t.name for t in registry.tables if t.layer == "gold"}
    for spec in metric_views.values():
        catalog, schema, table = spec["source"].split(".")
        assert (catalog, schema) == ("dev", "gold") and table in gold


# ------------------------------------------------------------------ dashboard


def test_dashboard_datasets_are_tokenised_metric_views(dashboard):
    assets = {d["name"]: d["asset_name"] for d in dashboard["datasets"]}
    assert assets == {
        "store_metrics": "__CATALOG__.__GOLD_SCHEMA__.sales_store_metrics",
        "category_metrics": "__CATALOG__.__GOLD_SCHEMA__.sales_category_metrics",
    }


def test_dashboard_fields_exist_in_metric_views(dashboard, metric_views):
    view_of = {d["name"]: d["asset_name"].rsplit(".", 1)[1] for d in dashboard["datasets"]}
    names = []
    for page in dashboard["pages"]:
        for item in page["layout"]:
            widget = item["widget"]
            names.append(widget["name"])
            for q in widget["queries"]:
                spec = metric_views[view_of[q["query"]["datasetName"]]]
                for field in q["query"]["fields"]:
                    expr = field["expression"]
                    measure = re.fullmatch(r"MEASURE\(`(\w+)`\)", expr)
                    if measure:
                        assert measure.group(1) in measure_names(spec), (widget["name"], expr)
                    else:
                        assert expr.strip("`") in dimension_names(spec), (widget["name"], expr)
            encoded = json.dumps(widget["spec"]["encodings"])
            field_names = {f["name"] for q in widget["queries"] for f in q["query"]["fields"]}
            for used in re.findall(r'"fieldName": "(\w+)"', encoded):
                assert used in field_names, (widget["name"], used)
    assert len(names) == len(set(names)), "widget names must be unique"


def test_dashboard_covers_requested_kpis(dashboard):
    text = json.dumps(dashboard)
    for kpi in REQUESTED_KPIS:
        assert f"MEASURE(`{kpi}`)" in text, kpi
