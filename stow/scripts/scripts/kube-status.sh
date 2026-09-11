#!/usr/bin/env bash
set -euo pipefail

# Resolve Stow's symlink and keep the caller's working directory for relative paths.
script_dir="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
export PYTHONPATH="$script_dir${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -P -m kube_status "$@"
