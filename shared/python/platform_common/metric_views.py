"""Render and publish Unity Catalog metric views kept as YAML files in a project.

Metric views are not a Databricks Asset Bundle resource type, so each project stores its
definitions under ``src/metric_views/<view_name>.yaml`` and a job task publishes them with
``CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML``. Redeploying an older git ref
and re-running the job therefore also rolls metric views back.

YAML files may contain ``${name}`` placeholders (e.g. ``${catalog}``). Only placeholders
are substituted, and every substituted value must be a plain identifier.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platform_common.identifiers import qualified_name, validate_identifier
from platform_common.templating import render

_MEASURE_REF = re.compile(r"MEASURE\(\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*\)", re.IGNORECASE)
SUPPORTED_VERSIONS = {"0.1", "1.1"}


@dataclass(frozen=True)
class MetricViewDefinition:
    name: str
    yaml_text: str


def load_definitions(directory: str | Path) -> list[MetricViewDefinition]:
    """Load ``*.yaml`` files; the file stem is the view name."""
    paths = sorted(Path(directory).glob("*.yaml"))
    return [
        MetricViewDefinition(validate_identifier(p.stem), p.read_text(encoding="utf-8"))
        for p in paths
    ]


def create_statement(
    definition: MetricViewDefinition, catalog: str, schema: str, values: Mapping[str, str]
) -> str:
    body = render(definition.yaml_text, values).rstrip()
    if "$$" in body:
        raise ValueError(f"{definition.name}: YAML must not contain '$$'")
    target = qualified_name(catalog, schema, definition.name)
    return f"CREATE OR REPLACE VIEW {target}\nWITH METRICS\nLANGUAGE YAML\nAS $$\n{body}\n$$"


def dimension_items(spec: Mapping[str, object]) -> list[Mapping[str, object]]:
    # "fields" is the current key; "dimensions" is accepted as a synonym.
    items = spec.get("dimensions", spec.get("fields", []))
    return list(items) if isinstance(items, list) else []


def measure_items(spec: Mapping[str, object]) -> list[Mapping[str, object]]:
    items = spec.get("measures", [])
    return list(items) if isinstance(items, list) else []


def dimension_names(spec: Mapping[str, object]) -> set[str]:
    return {str(item.get("name")) for item in dimension_items(spec)}


def measure_names(spec: Mapping[str, object]) -> set[str]:
    return {str(item.get("name")) for item in measure_items(spec)}


def validate_spec(spec: Mapping[str, object]) -> list[str]:
    """Structural checks that catch common mistakes before they reach the workspace.

    Returns a list of problems (empty when valid). Databricks performs the authoritative
    validation when the view is created; this is a fast local safety net.
    """
    problems: list[str] = []
    if str(spec.get("version")) not in SUPPORTED_VERSIONS:
        problems.append(f"version must be one of {sorted(SUPPORTED_VERSIONS)}")
    if not isinstance(spec.get("source"), str) or not str(spec.get("source")).strip():
        problems.append("source must be a non-empty string")
    if "dimensions" in spec and "fields" in spec:
        problems.append("use either 'dimensions' or 'fields', not both")
    if not measure_items(spec):
        problems.append("at least one measure is required")

    seen: set[str] = set()
    defined_measures: set[str] = set()
    for kind, items in (("dimension", dimension_items(spec)), ("measure", measure_items(spec))):
        for item in items:
            name, expr = item.get("name"), item.get("expr")
            if not isinstance(name, str) or not name:
                problems.append(f"{kind} without a name: {item!r}")
                continue
            if not isinstance(expr, str) or not expr.strip():
                problems.append(f"{kind} {name!r} has no expr")
                continue
            if name in seen:
                problems.append(f"duplicate name {name!r}")
            seen.add(name)
            if kind == "measure":
                for ref in _MEASURE_REF.findall(expr):
                    if ref not in defined_measures:
                        problems.append(f"measure {name!r} references {ref!r} before it is defined")
                defined_measures.add(name)
            elif _MEASURE_REF.search(expr):
                problems.append(f"dimension {name!r} must not use MEASURE()")
    return problems
