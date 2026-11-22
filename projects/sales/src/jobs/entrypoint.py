"""Single entry point for every Python job task of the sales bundle.

    python entrypoint.py <command> --catalog dev [options]

Commands
  generate-data         write missing days of synthetic POS/footfall files to the volume
  build-tables          build bronze/silver/gold Delta tables from src/tables/tables.yml
  publish-metric-views  CREATE OR REPLACE the metric views in src/metric_views/
  quality-checks        run integration checks (KPIs vs Python reference, reconciliations)

The same file runs locally (repo checkout) and in a serverless job, where the bundle
syncs ``projects/sales`` and ``shared/python`` under ``${workspace.file_path}``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PROJECT_REL = Path("projects") / "sales"


def _bootstrap(files_root: str | None) -> Path:
    """Put the project's ``src`` and ``shared/python`` on sys.path; return the project dir."""
    roots = []
    if files_root:
        roots.append(Path(files_root))
    if "__file__" in globals():
        roots.append(Path(__file__).resolve().parents[4])  # .../projects/sales/src/jobs/x.py
    for root in roots:
        project, shared = root / PROJECT_REL, root / "shared" / "python"
        if (project / "src" / "sales").is_dir() and shared.is_dir():
            for path in (project / "src", shared):
                if str(path) not in sys.path:
                    sys.path.insert(0, str(path))
            return project
    raise RuntimeError(f"cannot locate project sources under any of {roots}")


def _spark():
    from pyspark.sql import SparkSession

    return SparkSession.builder.getOrCreate()


def _values(args: argparse.Namespace) -> dict[str, str]:
    return {
        "catalog": args.catalog,
        "bronze_schema": args.bronze_schema,
        "silver_schema": args.silver_schema,
        "gold_schema": args.gold_schema,
    }


def _landing_path(args: argparse.Namespace) -> str:
    from platform_common.identifiers import validate_identifier

    parts = (args.catalog, args.bronze_schema, args.landing_volume)
    return "/Volumes/" + "/".join(validate_identifier(p) for p in parts)


def _atomic_write(path: Path, text: str) -> None:
    """Write via a hidden temp file so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"_tmp_{path.name}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def cmd_generate_data(args: argparse.Namespace, project: Path) -> None:
    from sales import generator

    landing = Path(_landing_path(args))
    start = date.fromisoformat(args.start_date)
    end = (
        date.fromisoformat(args.end_date)
        if args.end_date
        else datetime.now(UTC).date() - timedelta(days=1)
    )
    config = generator.GeneratorConfig(seed=args.seed, bad_record_rate=args.bad_record_rate)

    for dataset, text in generator.reference_files().items():
        _atomic_write(landing / dataset / f"{dataset}.json", text)

    marker_dir = landing / generator.COMPLETION_MARKER
    existing = os.listdir(marker_dir) if marker_dir.is_dir() else []
    days = generator.missing_dates(existing, start, end)[: args.max_days]
    for day in days:
        files = generator.build_day_files(day, config)
        # Traffic first, transactions last: the transactions file marks the day complete.
        for dataset in generator.DATASETS:
            _atomic_write(landing / dataset / generator.day_filename(dataset, day), files[dataset])
    print(f"generated {len(days)} day(s) into {landing} (window {start}..{end})")


def cmd_build_tables(args: argparse.Namespace, project: Path) -> None:
    from platform_common.tables import build_tables

    layers = [layer.strip() for layer in args.layers.split(",")] if args.layers else None
    results = build_tables(
        _spark(),
        project / "src" / "tables" / "tables.yml",
        _values(args),
        landing_path=_landing_path(args),
        layers=layers,
    )
    print(f"built {len(results)} table(s)")


def cmd_publish_metric_views(args: argparse.Namespace, project: Path) -> None:
    from platform_common.metric_views import create_statement, load_definitions

    spark = _spark()
    definitions = load_definitions(project / "src" / "metric_views")
    for definition in definitions:
        spark.sql(create_statement(definition, args.catalog, args.gold_schema, _values(args)))
        print(f"published metric view {args.catalog}.{args.gold_schema}.{definition.name}")


def cmd_quality_checks(args: argparse.Namespace, project: Path) -> None:
    from platform_common.quality import assert_all_passed, format_report, run_checks
    from sales.checks import build_checks

    spark = _spark()
    results = run_checks(
        build_checks(args.catalog, args.silver_schema, args.gold_schema),
        lambda sql: [tuple(row) for row in spark.sql(sql).collect()],
    )
    print(format_report(results))
    assert_all_passed(results)


COMMANDS = {
    "generate-data": cmd_generate_data,
    "build-tables": cmd_build_tables,
    "publish-metric-views": cmd_publish_metric_views,
    "quality-checks": cmd_quality_checks,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--bronze-schema", default="bronze")
    parser.add_argument("--silver-schema", default="silver")
    parser.add_argument("--gold-schema", default="gold")
    parser.add_argument("--landing-volume", default="sales_landing")
    parser.add_argument("--files-root", help="bundle file path (${workspace.file_path})")
    parser.add_argument("--layers", help="build-tables: comma-separated layers (default all)")
    parser.add_argument("--start-date", default="2025-08-01")
    parser.add_argument("--end-date", help="generate-data: last day (default yesterday UTC)")
    parser.add_argument("--max-days", type=int, default=730)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bad-record-rate", type=float, default=0.001)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    project = _bootstrap(args.files_root)
    COMMANDS[args.command](args, project)


if __name__ == "__main__":
    main()
