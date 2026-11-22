"""Decide which project bundles a change affects (prints a JSON array of project names).

Modes
  diff    --base <ref>        projects changed between merge-base(<ref>, HEAD) and HEAD.
                              Used by CI on pull requests.
  deploy  --env <dev|prod>    for each project, compare HEAD with the tag
                              ``deploy/<env>/<project>`` (moved after every successful
                              deploy). Projects without a tag count as affected. Robust to
                              skipped/cancelled runs: nothing is lost if a run never happens.
  select  --projects a,b|all  validate an explicit list (manual workflow runs).

A project is a folder ``projects/<name>/`` containing ``databricks.yml``. Changes under
GLOBAL_PATHS affect every project. ``--github-output`` also writes ``projects=<json>``
to $GITHUB_OUTPUT. Pure git + Python, so it runs unchanged in GitLab CI.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

PROJECTS_DIR = "projects"
GLOBAL_PATHS = ("shared/",)
DEPLOY_TAG = "deploy/{env}/{project}"


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def discover_projects(repo: Path) -> list[str]:
    root = repo / PROJECTS_DIR
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "databricks.yml").is_file())


def affected_by_paths(changed: Iterable[str], projects: Sequence[str]) -> list[str]:
    changed = [c.replace("\\", "/") for c in changed]
    if any(c.startswith(GLOBAL_PATHS) for c in changed):
        return sorted(projects)
    return sorted(p for p in projects if any(c.startswith(f"{PROJECTS_DIR}/{p}/") for c in changed))


def changed_files(repo: Path, base: str, head: str = "HEAD") -> list[str]:
    merge_base = git("merge-base", base, head, cwd=repo)
    output = git("diff", "--name-only", merge_base, head, cwd=repo)
    return [line for line in output.splitlines() if line]


def tag_exists(repo: Path, tag: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def deploy_candidates(repo: Path, env: str, head: str = "HEAD") -> list[str]:
    affected = []
    for project in discover_projects(repo):
        tag = DEPLOY_TAG.format(env=env, project=project)
        if not tag_exists(repo, tag):
            affected.append(project)
            continue
        paths = [f"{PROJECTS_DIR}/{project}/", *GLOBAL_PATHS]
        if git("diff", "--name-only", f"refs/tags/{tag}", head, "--", *paths, cwd=repo):
            affected.append(project)
    return affected


def select(repo: Path, requested: str) -> list[str]:
    known = discover_projects(repo)
    if requested.strip().lower() == "all":
        return known
    wanted = sorted({p.strip() for p in requested.split(",") if p.strip()})
    unknown = [p for p in wanted if p not in known]
    if unknown:
        raise SystemExit(f"unknown project(s) {unknown}; known: {known}")
    return wanted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["diff", "deploy", "select"])
    parser.add_argument("--base", help="diff: base ref, e.g. origin/develop")
    parser.add_argument("--env", choices=["dev", "prod"], help="deploy: environment")
    parser.add_argument("--projects", help="select: comma-separated names or 'all'")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "diff":
        if not args.base:
            parser.error("diff needs --base")
        projects = affected_by_paths(
            changed_files(args.repo, args.base, args.head), discover_projects(args.repo)
        )
    elif args.mode == "deploy":
        if not args.env:
            parser.error("deploy needs --env")
        projects = deploy_candidates(args.repo, args.env, args.head)
    else:
        if not args.projects:
            parser.error("select needs --projects")
        projects = select(args.repo, args.projects)

    payload = json.dumps(projects)
    print(payload)
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"projects={payload}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
