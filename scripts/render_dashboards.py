"""Render dashboard templates per bundle target, or capture an edited dashboard back.

Metric-view datasets in AI/BI dashboards need fully qualified names, which bundle
variables cannot reach inside the .lvdash.json file. Templates in
``projects/<p>/dashboards/`` therefore use tokens, rendered into the git-ignored
``projects/<p>/.build/dashboards/`` that the bundle deploys:

    __CATALOG__      -> the target's ``catalog`` variable
    __GOLD_SCHEMA__  -> the target's ``gold_schema`` variable

Usage
  python scripts/render_dashboards.py render  --project-dir projects/sales --target dev
  python scripts/render_dashboards.py capture --project-dir projects/sales --target dev
      (after ``databricks bundle generate dashboard --resource <key> --force`` wrote the
       edited dashboard into .build/, turn it back into a tokenised template)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TOKENS = {"__CATALOG__": "catalog", "__GOLD_SCHEMA__": "gold_schema"}
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TEMPLATE_DIR, BUILD_DIR = "dashboards", Path(".build") / "dashboards"
PATTERN = "*.lvdash.json"


def target_values(bundle: dict[str, Any], target: str) -> dict[str, str]:
    """Resolve the variables used by the tokens: defaults, then target overrides."""
    targets = bundle.get("targets") or {}
    if target not in targets:
        raise SystemExit(f"target {target!r} not found (available: {sorted(targets)})")
    values: dict[str, Any] = {}
    for name, spec in (bundle.get("variables") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            values[name] = spec["default"]
    values.update((targets[target] or {}).get("variables") or {})
    resolved = {}
    for token, variable in TOKENS.items():
        value = values.get(variable)
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise SystemExit(f"variable {variable!r} for target {target!r} must be an identifier")
        resolved[token] = value
    return resolved


def render_text(text: str, values: dict[str, str]) -> str:
    for token, value in values.items():
        text = text.replace(token, value)
    leftover = [t for t in TOKENS if t in text]
    if leftover:
        raise ValueError(f"unrendered tokens: {leftover}")
    return text


def capture(dashboard: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Replace this target's catalog.schema prefix with tokens in dataset references."""
    concrete = f"{values['__CATALOG__']}.{values['__GOLD_SCHEMA__']}."
    tokenised = "__CATALOG__.__GOLD_SCHEMA__."
    for dataset in dashboard.get("datasets", []):
        asset = dataset.get("asset_name")
        if isinstance(asset, str) and asset.startswith(concrete):
            dataset["asset_name"] = tokenised + asset[len(concrete) :]
        if "queryLines" in dataset:
            dataset["queryLines"] = [
                line.replace(concrete, tokenised) for line in dataset["queryLines"]
            ]
    return dashboard


def load_bundle(project_dir: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load((project_dir / "databricks.yml").read_text(encoding="utf-8")) or {}


def cmd_render(project_dir: Path, target: str) -> list[Path]:
    values = target_values(load_bundle(project_dir), target)
    out_dir = project_dir / BUILD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for template in sorted((project_dir / TEMPLATE_DIR).glob(PATTERN)):
        rendered = render_text(template.read_text(encoding="utf-8"), values)
        json.loads(rendered)  # fail fast on invalid JSON
        out = out_dir / template.name
        out.write_text(rendered, encoding="utf-8", newline="\n")
        written.append(out)
    return written


def cmd_capture(project_dir: Path, target: str) -> list[Path]:
    values = target_values(load_bundle(project_dir), target)
    written = []
    for built in sorted((project_dir / BUILD_DIR).glob(PATTERN)):
        data = capture(json.loads(built.read_text(encoding="utf-8")), values)
        out = project_dir / TEMPLATE_DIR / built.name
        out.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        written.append(out)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["render", "capture"])
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    handler = cmd_render if args.command == "render" else cmd_capture
    for path in handler(args.project_dir, args.target):
        print(f"{args.command}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
