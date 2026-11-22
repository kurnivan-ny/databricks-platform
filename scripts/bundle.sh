#!/usr/bin/env bash
# CI-agnostic wrapper around the Databricks CLI for ONE project bundle.
# GitHub Actions, GitLab CI and local shells all call this same script.
#
#   scripts/bundle.sh <project> <dev|prod> <command> [args]
#
# Commands
#   validate                 render dashboards, then `bundle validate`
#   deploy                   render dashboards, then `bundle deploy` (no auto-approve:
#                            destructive changes stop the deploy for a human to review)
#   run                      run the project's main job (default <project>_daily; RUN_JOB overrides)
#   verify                   execute every deployed dashboard widget query
#   summary                  `bundle summary`
#   capture-dashboard <key>  pull a dashboard edited in the UI back into its template (dev only)
#   destroy                  `bundle destroy` (refused for prod unless ALLOW_PROD_DESTROY=1)
#
# Auth comes from the environment: DATABRICKS_HOST + DATABRICKS_TOKEN (CI) or
# DATABRICKS_CONFIG_PROFILE (local). Nothing is hard-coded here.
set -euo pipefail

usage() { sed -n '2,20p' "$0" >&2; exit 2; }
die() { echo "error: $*" >&2; exit 1; }

[[ $# -ge 3 ]] || usage
project="$1" target="$2" command="$3"
shift 3

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$ROOT/projects/$project"
PY="${PYTHON:-python}"

[[ "$project" =~ ^[a-z][a-z0-9_]*$ ]] || die "invalid project name '$project'"
[[ -f "$project_dir/databricks.yml" ]] || die "no bundle at projects/$project"
[[ "$target" == "dev" || "$target" == "prod" ]] || die "target must be dev or prod"
command -v databricks >/dev/null || die "Databricks CLI not found (scripts/install_databricks_cli.sh)"

if [[ "$target" == "prod" && "${CI:-}" != "true" && "${ALLOW_LOCAL_PROD:-}" != "1" ]]; then
  die "prod is deployed by CI only (set ALLOW_LOCAL_PROD=1 to override deliberately)"
fi

render() { "$PY" "$ROOT/scripts/render_dashboards.py" render --project-dir "$project_dir" --target "$target"; }

cd "$project_dir"
echo "==> $project/$target: $command"
case "$command" in
  validate)
    render
    databricks bundle validate -t "$target"
    ;;
  deploy)
    render
    databricks bundle deploy -t "$target"
    ;;
  run)
    databricks bundle run -t "$target" "${RUN_JOB:-${project}_daily}"
    ;;
  verify)
    "$PY" "$ROOT/scripts/verify_dashboards.py" --project-dir "$project_dir" --target "$target"
    ;;
  summary)
    render
    databricks bundle summary -t "$target"
    ;;
  capture-dashboard)
    [[ $# -eq 1 ]] || die "usage: capture-dashboard <dashboard resource key>"
    [[ "$target" == "dev" ]] || die "edit and capture dashboards in dev only"
    render
    databricks bundle generate dashboard --resource "$1" -t "$target" --force
    "$PY" "$ROOT/scripts/render_dashboards.py" capture --project-dir "$project_dir" --target "$target"
    ;;
  destroy)
    if [[ "$target" == "prod" && "${ALLOW_PROD_DESTROY:-}" != "1" ]]; then
      die "refusing to destroy prod (set ALLOW_PROD_DESTROY=1 if you really mean it)"
    fi
    render
    databricks bundle destroy -t "$target"
    ;;
  *)
    usage
    ;;
esac
