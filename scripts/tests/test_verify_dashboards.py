import json
from pathlib import Path

import pytest
from verify_dashboards import widget_statements

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "projects"
    / "sales"
    / "dashboards"
    / "sales_overview.lvdash.json"
)


def test_metric_view_widgets_become_group_by_all_queries():
    dashboard = {
        "datasets": [{"name": "m", "asset_name": "dev.gold.mv"}],
        "pages": [
            {
                "name": "p",
                "layout": [
                    {
                        "widget": {
                            "name": "w",
                            "queries": [
                                {
                                    "name": "q",
                                    "query": {
                                        "datasetName": "m",
                                        "disaggregated": False,
                                        "fields": [
                                            {"name": "month", "expression": "`month`"},
                                            {"name": "atv", "expression": "MEASURE(`atv`)"},
                                        ],
                                    },
                                }
                            ],
                        }
                    }
                ],
            }
        ],
    }
    assert widget_statements(dashboard) == [
        (
            "p/w/q",
            "SELECT `month` AS `month`, MEASURE(`atv`) AS `atv` "
            "FROM dev.gold.mv GROUP BY ALL LIMIT 10",
        )
    ]


def test_sql_datasets_are_wrapped():
    dashboard = {
        "datasets": [{"name": "s", "queryLines": ["SELECT 1 AS x ", "FROM t"]}],
        "pages": [
            {
                "name": "p",
                "layout": [
                    {
                        "widget": {
                            "name": "w",
                            "queries": [
                                {
                                    "name": "q",
                                    "query": {
                                        "datasetName": "s",
                                        "disaggregated": True,
                                        "fields": [{"name": "x", "expression": "`x`"}],
                                    },
                                }
                            ],
                        }
                    }
                ],
            }
        ],
    }
    ((_, sql),) = widget_statements(dashboard)
    assert sql == "SELECT `x` AS `x` FROM (SELECT 1 AS x FROM t) AS q LIMIT 10"


def test_unknown_dataset_is_an_error():
    dashboard = {
        "datasets": [],
        "pages": [{"layout": [{"widget": {"queries": [{"query": {"datasetName": "nope"}}]}}]}],
    }
    with pytest.raises(ValueError):
        widget_statements(dashboard)


def test_every_sales_widget_produces_a_statement():
    dashboard = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    statements = widget_statements(dashboard)
    widgets = sum(len(p["layout"]) for p in dashboard["pages"])
    assert len(statements) >= widgets
    assert all("__CATALOG__.__GOLD_SCHEMA__." in sql for _, sql in statements)
