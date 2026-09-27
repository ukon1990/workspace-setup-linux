#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux ]]; then
  echo 'Skipping disks runtime: Linux only.'
  exit 0
fi

script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
venv="${DISKS_VENV:-$HOME/.local/share/disks/venv}"
python_bin="${PYTHON_BIN:-python3}"

if [[ "$venv" != /* || "$(basename "$venv")" != venv ||
      "$venv" == "$HOME" || "$(dirname "$venv")" == / ||
      "$venv/" == */../* || "$venv/" == */./* ]]; then
  echo 'DISKS_VENV must be a dedicated absolute path ending in /venv.' >&2
  exit 1
fi

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  echo "Would create disks runtime: $venv"
  echo "Would install: $script_dir/disks/requirements.txt"
  exit 0
fi

"$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' || {
  echo 'Python 3.12+ is required to set up disks.' >&2
  exit 1
}
if [[ ! -e "$venv" && ! -L "$venv" ]]; then
  "$python_bin" -m venv "$venv"
elif [[ ! -x "$venv/bin/python" ]] || ! "$venv/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "Disks runtime is broken: $venv. Move it aside and rerun setup." >&2
  exit 1
fi
"$venv/bin/python" -m pip install --disable-pip-version-check -q -r "$script_dir/disks/requirements.txt"
echo "Disks runtime: $venv"
