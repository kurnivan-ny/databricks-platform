import textwrap

import pytest
from fakes import FakeSpark
from platform_common.tables import (
    ExpectationFailed,
    build_table,
    build_tables,
    load_registry,
    merge_sql,
    parse_registry,
    validate_registry,
)

VALUES = {
    "catalog": "dev",
    "bronze_schema": "bronze",
    "silver_schema": "silver",
    "gold_schema": "gold",
}
SETTINGS = {
    "catalog": "catalog",
    "schemas": {"bronze": "bronze_schema", "silver": "silver_schema", "gold": "gold_schema"},
}


@pytest.fixture
def registry_dir(tmp_path):
    (tmp_path / "silver").mkdir()
    (tmp_path / "gold").mkdir()
    (tmp_path / "silver" / "lines.sql").write_text(
        "SELECT * FROM ${catalog}.${bronze_schema}.raw\n"
    )
    (tmp_path / "gold" / "daily.sql").write_text(
        "SELECT store_id, SUM(x) AS x FROM ${catalog}.${silver_schema}.lines GROUP BY store_id;\n"
    )
    (tmp_path / "tables.yml").write_text(
        textwrap.dedent(
            """
            settings:
              catalog: catalog
              schemas: {bronze: bronze_schema, silver: silver_schema, gold: gold_schema}
            tables:
              - name: raw
                layer: bronze
                files: transactions
                schema: "id STRING"
                write: append_new_files
              - name: lines
                layer: silver
                sql: silver/lines.sql
                write: merge
                keys: [txn_id, line_no]
                expect_or_drop: {positive_quantity: "quantity > 0"}
              - name: daily
                layer: gold
                sql: gold/daily.sql
                write: replace
                comment: Daily totals.
            """
        )
    )
    return tmp_path


def spec_named(registry, name):
    return next(t for t in registry.tables if t.name == name)


def test_registry_loads_and_validates(registry_dir):
    registry = load_registry(registry_dir / "tables.yml")
    assert validate_registry(registry) == []
    assert [t.name for t in registry.tables] == ["raw", "lines", "daily"]
    assert spec_named(registry, "lines").keys == ("txn_id", "line_no")


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        ({"name": "t", "layer": "platinum", "write": "replace", "sql": "x.sql"}, "unknown layer"),
        ({"name": "t", "layer": "gold", "write": "upsert", "sql": "x.sql"}, "unknown write mode"),
        ({"name": "t", "layer": "gold", "write": "replace"}, "exactly one of"),
        ({"name": "t", "layer": "gold", "write": "merge", "sql": "x.sql"}, "merge needs 'keys'"),
        ({"name": "t", "layer": "gold", "write": "replace", "sql": "missing.sql"}, "not found"),
        (
            {"name": "t", "layer": "bronze", "write": "append_new_files", "files": "f"},
            "need a 'schema'",
        ),
        (
            {"name": "t", "layer": "gold", "write": "append_new_files", "sql": "x.sql"},
            "needs a 'files'",
        ),
        (
            {"name": "t-1", "layer": "gold", "write": "replace", "sql": "x.sql"},
            "Invalid identifier",
        ),
        (
            {"name": "t", "layer": "gold", "write": "replace", "sql": "x.sql", "comment": "it's"},
            "quotes",
        ),
    ],
)
def test_invalid_entries_are_reported(tmp_path, entry, fragment):
    (tmp_path / "x.sql").write_text("SELECT 1")
    registry = parse_registry({"settings": SETTINGS, "tables": [entry]}, tmp_path)
    assert any(fragment in p for p in validate_registry(registry)), validate_registry(registry)


def test_unknown_keys_and_placeholders_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown keys"):
        parse_registry({"tables": [{"name": "t", "colour": "red"}]}, tmp_path)
    (tmp_path / "x.sql").write_text("SELECT * FROM ${nope}.t; SELECT 2")
    registry = parse_registry(
        {
            "settings": SETTINGS,
            "tables": [{"name": "t", "layer": "gold", "write": "replace", "sql": "x.sql"}],
        },
        tmp_path,
    )
    problems = " | ".join(validate_registry(registry))
    assert "unknown placeholders ['nope']" in problems
    assert "single SELECT" in problems


def test_replace_creates_table_from_rendered_sql(registry_dir):
    registry = load_registry(registry_dir / "tables.yml")
    spark = FakeSpark()
    result = build_table(spark, registry, spec_named(registry, "daily"), VALUES, log=lambda m: None)
    stage = spark.executed("CREATE OR REPLACE TEMP VIEW _stage_daily AS")[0]
    assert "FROM dev.silver.lines GROUP BY store_id" in stage and not stage.endswith(";")
    assert spark.executed(
        "CREATE OR REPLACE TABLE `dev`.`gold`.`daily` AS SELECT * FROM _stage_daily"
    )
    assert spark.executed("COMMENT ON TABLE `dev`.`gold`.`daily` IS 'Daily totals.'")
    assert result.rows_written == 10


def test_merge_into_existing_table_with_quarantine(registry_dir):
    registry = load_registry(registry_dir / "tables.yml")
    spark = FakeSpark(existing={"dev.silver.lines"}, counts={"lines_quarantine": 2})
    result = build_table(spark, registry, spec_named(registry, "lines"), VALUES, log=lambda m: None)
    quarantine = spark.executed("CREATE OR REPLACE TABLE `dev`.`silver`.`lines_quarantine`")[0]
    assert "'positive_quantity'" in quarantine and "_failed_rules" in quarantine
    (merge,) = spark.executed("MERGE INTO")
    assert "USING _stage_lines_valid AS s" in merge
    assert "t.`txn_id` <=> s.`txn_id` AND t.`line_no` <=> s.`line_no`" in merge
    assert merge.endswith("WHEN NOT MATCHED BY SOURCE THEN DELETE")
    assert result.quarantined == 2


def test_merge_creates_table_on_first_run(registry_dir):
    registry = load_registry(registry_dir / "tables.yml")
    spark = FakeSpark()
    build_table(spark, registry, spec_named(registry, "lines"), VALUES, log=lambda m: None)
    assert not spark.executed("MERGE INTO")
    assert spark.executed(
        "CREATE OR REPLACE TABLE `dev`.`silver`.`lines` AS SELECT * FROM _stage_lines_valid"
    )


def test_expect_or_fail_aborts_before_writing(tmp_path):
    (tmp_path / "x.sql").write_text("SELECT 1 AS a")
    registry = parse_registry(
        {
            "settings": SETTINGS,
            "tables": [
                {
                    "name": "t",
                    "layer": "gold",
                    "write": "replace",
                    "sql": "x.sql",
                    "expect_or_fail": {"a_positive": "a > 0"},
                }
            ],
        },
        tmp_path,
    )
    spark = FakeSpark(counts={"WHERE NOT COALESCE((a > 0), FALSE)": 3})
    with pytest.raises(ExpectationFailed, match="3 row"):
        build_table(spark, registry, registry.tables[0], VALUES, log=lambda m: None)
    assert not spark.executed("CREATE OR REPLACE TABLE")


def test_append_new_files_loads_only_unseen_files(registry_dir):
    registry = load_registry(registry_dir / "tables.yml")
    spark = FakeSpark(existing={"dev.bronze.raw"}, loaded_files=["t_2026-01-01.json"])
    files = ["t_2026-01-01.json", "t_2026-01-02.json", "_tmp_t_2026-01-03.json", "notes.txt"]
    build_table(
        spark,
        registry,
        spec_named(registry, "raw"),
        VALUES,
        landing_path="/Volumes/dev/bronze/landing",
        list_files=lambda folder: files,
        log=lambda m: None,
    )
    loads = [r[1] for r in spark.reads if r[0] == "load"]
    assert loads == ["/Volumes/dev/bronze/landing/transactions/t_2026-01-02.json"]
    assert spark.executed("INSERT INTO `dev`.`bronze`.`raw` SELECT * FROM _stage_raw")


def test_append_new_files_noop_when_nothing_new(registry_dir):
    registry = load_registry(registry_dir / "tables.yml")
    spark = FakeSpark(existing={"dev.bronze.raw"}, loaded_files=["a.json"])
    result = build_table(
        spark,
        registry,
        spec_named(registry, "raw"),
        VALUES,
        landing_path="/Volumes/x",
        list_files=lambda folder: ["a.json"],
        log=lambda m: None,
    )
    assert result.rows_written == 0
    assert not spark.executed("INSERT") and not spark.executed("CREATE OR REPLACE TABLE")


def test_build_tables_filters_layers_and_checks_values(registry_dir):
    spark = FakeSpark()
    results = build_tables(
        spark, registry_dir / "tables.yml", VALUES, layers=["gold"], log=lambda m: None
    )
    assert [r.table for r in results] == ["`dev`.`gold`.`daily`"]
    with pytest.raises(KeyError):
        build_tables(spark, registry_dir / "tables.yml", {"catalog": "dev"}, log=lambda m: None)
    with pytest.raises(ValueError, match="unknown layer"):
        build_tables(
            spark, registry_dir / "tables.yml", VALUES, layers=["platinum"], log=lambda m: None
        )


def test_merge_sql_without_delete():
    sql = merge_sql("`c`.`s`.`t`", "v", ["id"], delete_missing=False)
    assert "NOT MATCHED BY SOURCE" not in sql
