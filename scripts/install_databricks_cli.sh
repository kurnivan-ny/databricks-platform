#!/usr/bin/env bash
# Install the pinned Databricks CLI (version in .databricks-cli-version) with SHA-256
# verification. Works on GitHub-hosted runners, GitLab runners and Linux/macOS hosts.
#
#   scripts/install_databricks_cli.sh [install_dir]     (default: $HOME/.local/bin)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${DATABRICKS_CLI_VERSION:-$(tr -d '[:space:]' < "$ROOT/.databricks-cli-version")}"
DEST="${1:-$HOME/.local/bin}"

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) echo "unsupported OS $(uname -s); on Windows see README (Windows setup)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  arm64 | aarch64) arch=arm64 ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac

asset="databricks_cli_${VERSION}_${os}_${arch}.zip"
base="https://github.com/databricks/cli/releases/download/v${VERSION}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL --retry 3 -o "$tmp/$asset" "$base/$asset"
curl -fsSL --retry 3 -o "$tmp/SHA256SUMS" "$base/databricks_cli_${VERSION}_SHA256SUMS"

expected="$(awk -v f="$asset" '$2 == f {print $1}' "$tmp/SHA256SUMS")"
if command -v sha256sum >/dev/null; then
  actual="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
else
  actual="$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')"
fi
if [[ -z "$expected" || "$expected" != "$actual" ]]; then
  echo "checksum mismatch for $asset (expected '$expected', got '$actual')" >&2
  exit 1
fi

mkdir -p "$DEST" "$tmp/unpacked"
unzip -q -o "$tmp/$asset" -d "$tmp/unpacked"
install -m 0755 "$tmp/unpacked/databricks" "$DEST/databricks"
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$DEST" >> "$GITHUB_PATH"
fi
"$DEST/databricks" --version
