import pytest
from platform_common.metric_views import (
    create_statement,
    dimension_names,
    load_definitions,
    measure_names,
    validate_spec,
)

VALID = {
    "version": 1.1,  # YAML parses 1.1 as a float
    "source": "dev.gold.t",
    "dimensions": [{"name": "month", "expr": "month"}],
    "measures": [
        {"name": "net_sales", "expr": "SUM(net_sales)"},
        {"name": "transactions", "expr": "SUM(transactions)"},
        {"name": "atv", "expr": "MEASURE(net_sales) / NULLIF(MEASURE(`transactions`), 0)"},
    ],
}


def test_valid_spec_has_no_problems():
    assert validate_spec(VALID) == []
    assert dimension_names(VALID) == {"month"}
    assert measure_names(VALID) == {"net_sales", "transactions", "atv"}


def test_measure_referenced_before_definition_is_reported():
    spec = dict(VALID, measures=list(reversed(VALID["measures"])))
    assert any("before it is defined" in p for p in validate_spec(spec))


def test_other_problems_are_reported():
    spec = {
        "version": "9.9",
        "source": "",
        "dimensions": [{"name": "m", "expr": "MEASURE(x)"}, {"name": "m", "expr": "m"}],
        "measures": [{"name": "x", "expr": ""}],
    }
    problems = " | ".join(validate_spec(spec))
    for fragment in ("version", "source", "must not use MEASURE", "duplicate name", "no expr"):
        assert fragment in problems


def test_create_statement_renders_and_wraps(tmp_path):
    (tmp_path / "my_view.yaml").write_text("version: 1.1\nsource: ${catalog}.${gold_schema}.t\n")
    (definition,) = load_definitions(tmp_path)
    sql = create_statement(definition, "dev", "gold", {"catalog": "dev", "gold_schema": "gold"})
    assert sql.startswith(
        "CREATE OR REPLACE VIEW `dev`.`gold`.`my_view`\nWITH METRICS\nLANGUAGE YAML\nAS $$"
    )
    assert "source: dev.gold.t" in sql
    assert sql.endswith("\n$$")


def test_create_statement_rejects_dollar_quote(tmp_path):
    (tmp_path / "v.yaml").write_text("comment: $$ nope\n")
    (definition,) = load_definitions(tmp_path)
    with pytest.raises(ValueError):
        create_statement(definition, "dev", "gold", {})


def test_view_name_must_be_identifier(tmp_path):
    (tmp_path / "bad-name.yaml").write_text("version: 1.1\n")
    with pytest.raises(ValueError):
        load_definitions(tmp_path)
