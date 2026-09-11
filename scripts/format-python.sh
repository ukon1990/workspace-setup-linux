#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

case "${1:-}" in
  --help|-h)
    echo 'Usage: scripts/format-python.sh [--check]'
    echo 'Format all repository Python files and apply safe lint fixes.'
    echo '--check reports formatting/lint issues without changing files.'
    exit 0
    ;;
  ''|--check) ;;
  *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then
  echo 'Expected no arguments or --check.' >&2
  exit 2
fi

if [[ -x "$repo_root/.venv/bin/ruff" ]]; then
  ruff_cmd="$repo_root/.venv/bin/ruff"
elif command -v ruff >/dev/null 2>&1; then
  ruff_cmd="$(command -v ruff)"
else
  echo 'Ruff is missing. Run:' >&2
  echo '  python3 -m venv .venv' >&2
  echo '  .venv/bin/python -m pip install -r requirements-dev.txt' >&2
  exit 1
fi

status=0
if [[ "${1:-}" == --check ]]; then
  "$ruff_cmd" check . || status=1
  "$ruff_cmd" format --check . || status=1
else
  "$ruff_cmd" check --fix . || status=1
  "$ruff_cmd" format . || status=1
fi
exit "$status"
