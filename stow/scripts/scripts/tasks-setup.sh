#!/usr/bin/env bash
set -euo pipefail

resolve_script() {
  local source="$1" directory
  while [[ -L "$source" ]]; do
    directory="$(cd -P "$(dirname "$source")" && pwd)"
    source="$(readlink "$source")"
    [[ "$source" == /* ]] || source="$directory/$source"
  done
  directory="$(cd -P "$(dirname "$source")" && pwd)"
  printf '%s/%s\n' "$directory" "$(basename "$source")"
}

script_path="$(resolve_script "${BASH_SOURCE[0]}")"
script_dir="$(dirname "$script_path")"
requirements="$script_dir/tasks/requirements.txt"
venv="${TASKS_VENV-$HOME/.local/share/tasks/venv}"
python_bin="${PYTHON_BIN:-python3}"

[[ -n "$venv" ]] || {
  echo "TASKS_VENV cannot be empty. Use a dedicated path ending in /venv." >&2
  exit 1
}
[[ "$venv" == /* ]] || {
  echo "TASKS_VENV must be an absolute, dedicated path ending in /venv: $venv" >&2
  exit 1
}
while [[ "$venv" != / && "$venv" == */ ]]; do
  venv="${venv%/}"
done
home="${HOME%/}"
[[ -n "$home" ]] || home=/

if [[ "$venv" == / || "$venv" == "$home" || "$(dirname "$venv")" == / ||
  "$(basename "$venv")" != venv || "$venv/" == */./* || "$venv/" == */../* ]]; then
  echo "Unsafe TASKS_VENV: $venv" >&2
  echo "Use a dedicated absolute path ending in /venv, such as: $home/.local/share/tasks/venv" >&2
  exit 1
fi

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  echo "Would create tasks runtime: $venv"
  echo "Would install: $requirements"
  echo "Tasks runtime: $venv"
  exit 0
fi

command -v "$python_bin" >/dev/null 2>&1 || {
  echo "Python 3.12+ is required to set up tasks." >&2
  exit 1
}
"$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' || {
  echo "Python 3.12+ is required to set up tasks (textual-image needs it)." >&2
  exit 1
}

if [[ ! -e "$venv" && ! -L "$venv" ]]; then
  echo "Creating tasks runtime: $venv"
  LC_ALL=C LANG=C "$python_bin" -m venv "$venv"
elif [[ ! -x "$venv/bin/python" ]] ||
  ! "$venv/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "Tasks runtime is broken: $venv" >&2
  printf 'Move or remove it, then run: TASKS_VENV=%q %q\n' "$venv" "$script_path" >&2
  exit 1
fi

LC_ALL=C LANG=C "$venv/bin/python" -m pip install \
  --disable-pip-version-check -q -r "$requirements"
echo "Tasks runtime: $venv"
