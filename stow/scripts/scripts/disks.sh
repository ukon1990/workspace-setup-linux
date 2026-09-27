#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux ]]; then
  echo 'disks is Linux-only (ntfs3, util-linux, and systemd).' >&2
  exit 1
fi

# Linux readlink resolves both Stow directory links and direct script links.
script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
venv="${DISKS_VENV:-$HOME/.local/share/disks/venv}"

if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  exec /usr/bin/python3 -I -c \
    'import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("disks",run_name="__main__")' \
    "$script_dir" "$@"
fi
if [[ $EUID -eq 0 ]]; then
  echo 'Run disks.sh as your regular user. It prompts for sudo when needed.' >&2
  exit 1
fi

runtime_ready() {
  [[ -x "$venv/bin/python" ]] && "$venv/bin/python" -I -c 'import textual' >/dev/null 2>&1
}

if ! runtime_ready; then
  if [[ -t 0 ]]; then
    read -r -p 'The disks runtime is missing. Run setup now? [y/N] ' answer || answer=
    if [[ "$answer" == [Yy]* ]]; then
      "$script_dir/disks-setup.sh"
    fi
  fi
  if ! runtime_ready; then
    printf 'Run: %q\n' "$script_dir/disks-setup.sh" >&2
    exit 1
  fi
fi

exec "$venv/bin/python" -I -c \
  'import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("disks",run_name="__main__")' \
  "$script_dir" "$@"
