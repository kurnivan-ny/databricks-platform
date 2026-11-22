import pytest
from platform_common.identifiers import qualified_name, validate_identifier
from platform_common.templating import placeholders, render


@pytest.mark.parametrize("name", ["dev", "prod", "gold", "sales_store_daily", "_x1"])
def test_valid_identifiers(name):
    assert validate_identifier(name) == name


@pytest.mark.parametrize("name", ["", "1abc", "dev.gold", "a-b", "x; DROP TABLE y", "a b", None])
def test_invalid_identifiers(name):
    with pytest.raises(ValueError):
        validate_identifier(name)


def test_qualified_name_backquotes_parts():
    assert qualified_name("dev", "gold", "sales") == "`dev`.`gold`.`sales`"


def test_qualified_name_requires_parts():
    with pytest.raises(ValueError):
        qualified_name()


def test_render_substitutes_known_placeholders():
    sql = "SELECT * FROM ${catalog}.${gold_schema}.t WHERE x = '${catalog}'"
    assert render(sql, {"catalog": "dev", "gold_schema": "gold"}) == (
        "SELECT * FROM dev.gold.t WHERE x = 'dev'"
    )


def test_render_rejects_unknown_placeholder():
    with pytest.raises(KeyError):
        render("${missing}", {})


def test_render_rejects_injection_values():
    with pytest.raises(ValueError):
        render("${catalog}", {"catalog": "dev; DROP CATALOG prod"})


def test_placeholders_lists_names():
    assert placeholders("${a} ${b} ${a} $c") == {"a", "b"}
