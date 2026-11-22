#!/usr/bin/env bash
# Record a successful deployment in git so the next run only deploys what changed and
# so PROD releases can be rolled back to.
#
#   scripts/mark_deployed.sh <dev|prod> <project> [<commit>]
#
# * Moves  deploy/<env>/<project>          -> commit (used by changed_projects.py deploy)
# * prod also creates  release/<project>/<UTC timestamp>  (immutable rollback points)
set -euo pipefail

env="$1" project="$2" commit="${3:-$(git rev-parse HEAD)}"
[[ "$env" == "dev" || "$env" == "prod" ]] || { echo "env must be dev or prod" >&2; exit 1; }
[[ "$project" =~ ^[a-z][a-z0-9_]*$ ]] || { echo "invalid project '$project'" >&2; exit 1; }

moving="deploy/$env/$project"
git tag -f "$moving" "$commit"
git push -f origin "refs/tags/$moving"
echo "tagged $moving -> $commit"

if [[ "$env" == "prod" ]]; then
  release="release/$project/$(date -u +%Y%m%d-%H%M%S)"
  git tag "$release" "$commit"
  git push origin "refs/tags/$release"
  echo "tagged $release -> $commit (rollback point)"
fi
