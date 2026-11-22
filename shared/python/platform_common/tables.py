"""Config-driven table builder: SQL holds the logic, a YAML registry drives execution.

Every table is a plain managed Delta table (no streaming tables, no Lakeflow pipeline).
A project keeps ``SELECT`` statements in ``.sql`` files and lists its tables, in build
order, in a registry such as ``projects/sales/src/tables/tables.yml``::

    settings:
      catalog: catalog                       # value key for the catalog
      schemas: {bronze: bronze_schema, silver: silver_schema, gold: gold_schema}
    tables:
      - name: sales_transactions_raw         # bronze: new landing files only
        layer: bronze
        files: transactions                  # folder under the landing path
        format: json
        schema: "txn_id STRING, ..."
        write: append_new_files
      - name: sales_transaction_lines        # silver: upsert by key
        layer: silver
        sql: silver/sales_transaction_lines.sql
        write: merge
        keys: [txn_id, line_no]
        expect_or_drop: {positive_quantity: "quantity > 0"}
      - name: sales_store_daily              # gold: full rebuild
        layer: gold
        sql: gold/sales_store_daily.sql
        write: replace

Write modes
  append_new_files  load only files not yet recorded in ``_source_file`` (idempotent)
  replace           CREATE OR REPLACE TABLE ... AS SELECT
  merge             MERGE on ``keys``; rows missing from the source are deleted unless
                    ``delete_missing: false``

Expectations (SQL boolean expressions; NULL counts as a violation)
  expect            count and report violations, keep the rows
  expect_or_drop    exclude violating rows; ``<table>_quarantine`` holds the latest build's
                    rejects with the names of the failed rules
  expect_or_fail    abort the build if any row violates the rule

SQL files may use ``${catalog}`` and ``${<schema key>}`` placeholders, rendered from the
values passed in (identifiers only). Tables are built in registry order, so a table may
only read tables listed before it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from platform_common.identifiers import qualified_name, validate_identifier
from platform_common.templating import placeholders, render

WRITE_MODES = frozenset({"append_new_files", "replace", "merge"})
EXPECTATION_KEYS = ("expect", "expect_or_drop", "expect_or_fail")
SOURCE_FILE_COLUMN = "_source_file"
FAILED_RULES_COLUMN = "_failed_rules"
_LINE_COMMENT = re.compile(r"--[^\n]*")


@dataclass(frozen=True)
class TableSpec:
    name: str
    layer: str
    write: str
    comment: str = ""
    sql: str | None = None  # path relative to the registry file
    files: str | None = None  # folder relative to the landing path
    format: str = "json"
    schema: str | None = None  # DDL schema for file sources (no inference drift)
    keys: tuple[str, ...] = ()
    delete_missing: bool = True
    expect: dict[str, str] = field(default_factory=dict)
    expect_or_drop: dict[str, str] = field(default_factory=dict)
    expect_or_fail: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Registry:
    base_dir: Path
    catalog_key: str
    schema_keys: dict[str, str]  # layer -> value key
    tables: tuple[TableSpec, ...]

    @property
    def value_keys(self) -> list[str]:
        return [self.catalog_key, *self.schema_keys.values()]

    def layers(self) -> list[str]:
        return list(self.schema_keys)


@dataclass(frozen=True)
class BuildResult:
    table: str
    write: str
    rows_written: int | None = None
    quarantined: int = 0
    warnings: dict[str, int] = field(default_factory=dict)


class ExpectationFailed(RuntimeError):
    """An ``expect_or_fail`` rule was violated; nothing was written for that table."""


# --------------------------------------------------------------------------- registry


def parse_registry(data: Mapping[str, Any], base_dir: str | Path) -> Registry:
    settings = data.get("settings") or {}
    known = set(TableSpec.__dataclass_fields__)
    tables = []
    for raw in data.get("tables") or []:
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"table {raw.get('name')!r}: unknown keys {sorted(unknown)}")
        values = dict(raw)
        values["keys"] = tuple(values.get("keys") or ())
        for key in EXPECTATION_KEYS:
            values[key] = dict(values.get(key) or {})
        tables.append(TableSpec(**values))
    return Registry(
        base_dir=Path(base_dir),
        catalog_key=settings.get("catalog", "catalog"),
        schema_keys=dict(settings.get("schemas") or {}),
        tables=tuple(tables),
    )


def load_registry(path: str | Path) -> Registry:
    import yaml  # PyYAML is preinstalled on Databricks runtimes; in requirements-dev locally

    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        return parse_registry(yaml.safe_load(handle) or {}, path.parent)


def _check_identifier(label: str, value: str, problems: list[str]) -> None:
    try:
        validate_identifier(value)
    except ValueError as exc:
        problems.append(f"{label}: {exc}")


def validate_registry(registry: Registry) -> list[str]:
    """Return a list of problems (empty when valid). Runs locally in unit tests and
    again at build time, before anything touches the workspace."""
    problems: list[str] = []
    allowed = set(registry.value_keys)
    seen: set[str] = set()
    if not registry.tables:
        problems.append("registry defines no tables")
    for spec in registry.tables:
        label = f"table {spec.name!r}"
        _check_identifier(label, spec.name, problems)
        if spec.name in seen:
            problems.append(f"{label}: duplicate name")
        seen.add(spec.name)
        if spec.layer not in registry.schema_keys:
            problems.append(f"{label}: unknown layer {spec.layer!r}")
        if spec.write not in WRITE_MODES:
            problems.append(f"{label}: unknown write mode {spec.write!r}")
        if bool(spec.sql) == bool(spec.files):
            problems.append(f"{label}: set exactly one of 'sql' or 'files'")
        if spec.files and not spec.schema:
            problems.append(f"{label}: file sources need a 'schema'")
        if spec.write == "append_new_files" and not spec.files:
            problems.append(f"{label}: append_new_files needs a 'files' source")
        if spec.write == "merge":
            if not spec.keys:
                problems.append(f"{label}: merge needs 'keys'")
            for key in spec.keys:
                _check_identifier(f"{label} key", key, problems)
        if "'" in spec.comment or "\\" in spec.comment:
            problems.append(f"{label}: comment must not contain quotes or backslashes")
        if spec.sql:
            sql_file = registry.base_dir / spec.sql
            if not sql_file.is_file():
                problems.append(f"{label}: SQL file {spec.sql!r} not found")
            else:
                text = sql_file.read_text(encoding="utf-8")
                unknown = placeholders(text) - allowed
                if unknown:
                    problems.append(f"{label}: unknown placeholders {sorted(unknown)}")
                code = _LINE_COMMENT.sub("", text).strip().rstrip(";")
                if ";" in code:
                    problems.append(f"{label}: SQL file must contain a single SELECT statement")
        for key in EXPECTATION_KEYS:
            for rule, constraint in getattr(spec, key).items():
                _check_identifier(f"{label} rule", rule, problems)
                if not isinstance(constraint, str) or not constraint.strip():
                    problems.append(f"{label}: expectation {rule!r} has an empty constraint")
    return problems


# --------------------------------------------------------------------------- SQL text


def table_name(registry: Registry, spec: TableSpec, values: Mapping[str, str]) -> str:
    return qualified_name(
        values[registry.catalog_key], values[registry.schema_keys[spec.layer]], spec.name
    )


def render_select(registry: Registry, spec: TableSpec, values: Mapping[str, str]) -> str:
    text = (registry.base_dir / str(spec.sql)).read_text(encoding="utf-8")
    return render(text, values).strip().rstrip(";")


def _all_rules(spec: TableSpec) -> dict[str, str]:
    return {**spec.expect_or_fail, **spec.expect_or_drop, **spec.expect}


def violation_count_sql(view: str, constraint: str) -> str:
    return f"SELECT COUNT(*) FROM {view} WHERE NOT COALESCE(({constraint}), FALSE)"


def passing_predicate(rules: Mapping[str, str]) -> str:
    return " AND ".join(f"COALESCE(({c}), FALSE)" for c in rules.values()) or "TRUE"


def failed_rules_expr(rules: Mapping[str, str]) -> str:
    parts = [f"IF(COALESCE(({c}), FALSE), NULL, '{name}')" for name, c in rules.items()]
    return f"filter(array({', '.join(parts)}), x -> x IS NOT NULL)"


def merge_sql(target: str, source_view: str, keys: Iterable[str], delete_missing: bool) -> str:
    condition = " AND ".join(f"t.`{k}` <=> s.`{k}`" for k in keys)
    statement = (
        f"MERGE INTO {target} AS t USING {source_view} AS s ON {condition} "
        "WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *"
    )
    if delete_missing:
        statement += " WHEN NOT MATCHED BY SOURCE THEN DELETE"
    return statement


# --------------------------------------------------------------------------- execution


def _scalar(spark: Any, sql: str) -> int:
    return int(spark.sql(sql).collect()[0][0])


def _apply_expectations(
    spark: Any, spec: TableSpec, target: str, stage_view: str, log: Callable[[str], None]
) -> tuple[str, int, dict[str, int]]:
    """Enforce expectations on ``stage_view``; returns (view to write, quarantined, warnings)."""
    for rule, constraint in spec.expect_or_fail.items():
        bad = _scalar(spark, violation_count_sql(stage_view, constraint))
        if bad:
            raise ExpectationFailed(f"{target}: {bad} row(s) violate {rule!r} ({constraint})")

    warnings = {}
    for rule, constraint in spec.expect.items():
        bad = _scalar(spark, violation_count_sql(stage_view, constraint))
        if bad:
            warnings[rule] = bad
            log(f"WARN {target}: {bad} row(s) violate {rule!r} ({constraint}); rows kept")

    if not spec.expect_or_drop:
        return stage_view, 0, warnings

    rules = spec.expect_or_drop
    quarantine = target[:-1] + "_quarantine`"
    rejected = (
        f"SELECT *, {failed_rules_expr(rules)} AS {FAILED_RULES_COLUMN}, "
        f"current_timestamp() AS _quarantined_at "
        f"FROM {stage_view} WHERE NOT ({passing_predicate(rules)})"
    )
    # SQL sources are recomputed in full each build, so the quarantine table holds the
    # rejects of the *latest* build (replaced, not appended — no duplicates over time).
    spark.sql(f"CREATE OR REPLACE TABLE {quarantine} AS {rejected}")
    quarantined = _scalar(spark, f"SELECT COUNT(*) FROM {quarantine}")
    if quarantined:
        log(f"{target}: {quarantined} row(s) rejected -> {quarantine}")
    valid_view = f"{stage_view}_valid"
    spark.sql(
        f"CREATE OR REPLACE TEMP VIEW {valid_view} AS "
        f"SELECT * FROM {stage_view} WHERE {passing_predicate(rules)}"
    )
    return valid_view, quarantined, warnings


def _new_files(
    spark: Any, target: str, folder: str, fmt: str, list_files: Callable[[str], list[str]]
) -> list[str]:
    try:
        names = list_files(folder)
    except FileNotFoundError:
        return []
    candidates = sorted(n for n in names if n.endswith(f".{fmt}") and not n.startswith(("_", ".")))
    if not candidates or not spark.catalog.tableExists(target.replace("`", "")):
        return candidates
    loaded = {
        PurePosixPath(str(row[0])).name
        for row in spark.sql(f"SELECT DISTINCT {SOURCE_FILE_COLUMN} FROM {target}").collect()
    }
    return [n for n in candidates if n not in loaded]


def build_table(
    spark: Any,
    registry: Registry,
    spec: TableSpec,
    values: Mapping[str, str],
    landing_path: str | None = None,
    list_files: Callable[[str], list[str]] = os.listdir,
    log: Callable[[str], None] = print,
) -> BuildResult:
    target = table_name(registry, spec, values)
    stage_view = f"_stage_{spec.name}"

    if spec.files:
        if not landing_path:
            raise ValueError(f"{target}: a landing path is required for file sources")
        folder = f"{landing_path.rstrip('/')}/{spec.files}"
        if spec.write == "append_new_files":
            paths = [
                f"{folder}/{n}" for n in _new_files(spark, target, folder, spec.format, list_files)
            ]
            if not paths:
                log(f"{target}: no new files")
                return BuildResult(target, spec.write, rows_written=0)
        else:
            paths = [folder]
        frame = (
            spark.read.format(spec.format)
            .schema(spec.schema)
            .load(paths if len(paths) > 1 else paths[0])
            .selectExpr(
                "*",
                f"_metadata.file_path AS {SOURCE_FILE_COLUMN}",
                "current_timestamp() AS _ingested_at",
            )
        )
        frame.createOrReplaceTempView(stage_view)
    else:
        spark.sql(
            f"CREATE OR REPLACE TEMP VIEW {stage_view} AS {render_select(registry, spec, values)}"
        )

    write_view, quarantined, warnings = _apply_expectations(spark, spec, target, stage_view, log)
    rows = _scalar(spark, f"SELECT COUNT(*) FROM {write_view}")
    exists = spark.catalog.tableExists(target.replace("`", ""))

    if spec.write == "replace" or not exists:
        spark.sql(f"CREATE OR REPLACE TABLE {target} AS SELECT * FROM {write_view}")
    elif spec.write == "append_new_files":
        spark.sql(f"INSERT INTO {target} SELECT * FROM {write_view}")
    else:
        spark.sql(merge_sql(target, write_view, spec.keys, spec.delete_missing))
    if spec.comment:
        spark.sql(f"COMMENT ON TABLE {target} IS '{spec.comment}'")
    log(f"{target}: {spec.write} ({rows} source rows, {quarantined} quarantined)")
    return BuildResult(target, spec.write, rows, quarantined, warnings)


def build_tables(
    spark: Any,
    registry_path: str | Path,
    values: Mapping[str, str],
    landing_path: str | None = None,
    layers: Iterable[str] | None = None,
    list_files: Callable[[str], list[str]] = os.listdir,
    log: Callable[[str], None] = print,
) -> list[BuildResult]:
    """Validate the registry, then build its tables (optionally only some layers) in order."""
    registry = load_registry(registry_path)
    problems = validate_registry(registry)
    if problems:
        raise ValueError("invalid table registry:\n  " + "\n  ".join(problems))
    missing = [k for k in registry.value_keys if k not in values]
    if missing:
        raise KeyError(f"missing values for {missing}")
    wanted = set(layers) if layers else set(registry.layers())
    unknown = wanted - set(registry.layers())
    if unknown:
        raise ValueError(f"unknown layer(s) {sorted(unknown)}")
    return [
        build_table(spark, registry, spec, values, landing_path, list_files, log)
        for spec in registry.tables
        if spec.layer in wanted
    ]
