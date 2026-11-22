import json
import shutil
from pathlib import Path

import pytest
from render_dashboards import capture, cmd_capture, cmd_render, render_text, target_values

BUNDLE = {
    "variables": {"catalog": {"description": "x"}, "gold_schema": {"default": "gold"}},
    "targets": {
        "dev": {"variables": {"catalog": "dev"}},
        "prod": {"variables": {"catalog": "prod"}},
    },
}
SALES = Path(__file__).resolve().parents[2] / "projects" / "sales"


def test_target_values():
    assert target_values(BUNDLE, "prod") == {"__CATALOG__": "prod", "__GOLD_SCHEMA__": "gold"}
    with pytest.raises(SystemExit):
        target_values(BUNDLE, "qa")
    with pytest.raises(SystemExit):
        target_values({"targets": {"dev": {}}}, "dev")  # catalog unresolved


def test_render_text_and_leftover_detection():
    values = {"__CATALOG__": "dev", "__GOLD_SCHEMA__": "gold"}
    assert render_text("__CATALOG__.__GOLD_SCHEMA__.mv", values) == "dev.gold.mv"
    with pytest.raises(ValueError):
        render_text("__CATALOG__", {"__CATALOG__": "__GOLD_SCHEMA__"})


def test_capture_restores_tokens():
    values = {"__CATALOG__": "dev", "__GOLD_SCHEMA__": "gold"}
    data = {
        "datasets": [{"asset_name": "dev.gold.mv"}, {"queryLines": ["SELECT * FROM dev.gold.t"]}]
    }
    out = capture(data, values)
    assert out["datasets"][0]["asset_name"] == "__CATALOG__.__GOLD_SCHEMA__.mv"
    assert out["datasets"][1]["queryLines"] == ["SELECT * FROM __CATALOG__.__GOLD_SCHEMA__.t"]


@pytest.mark.parametrize("target", ["dev", "prod"])
def test_render_capture_roundtrip_on_sales_project(tmp_path, target):
    project = tmp_path / "sales"
    shutil.copytree(SALES / "dashboards", project / "dashboards")
    shutil.copy(SALES / "databricks.yml", project / "databricks.yml")

    (rendered,) = cmd_render(project, target)
    data = json.loads(rendered.read_text(encoding="utf-8"))
    assert {d["asset_name"].split(".")[0] for d in data["datasets"]} == {target}

    original = json.loads((project / "dashboards" / rendered.name).read_text(encoding="utf-8"))
    cmd_capture(project, target)
    assert (
        json.loads((project / "dashboards" / rendered.name).read_text(encoding="utf-8")) == original
    )
