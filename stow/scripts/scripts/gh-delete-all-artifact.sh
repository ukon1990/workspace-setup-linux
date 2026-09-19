#!/usr/bin/env bash
set -euo pipefail

# Resolve Stow's symlink and keep the caller's working directory.
script_dir="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
exec python3 "$script_dir/gh-delete-all-artifact/cli.py" "$@"
