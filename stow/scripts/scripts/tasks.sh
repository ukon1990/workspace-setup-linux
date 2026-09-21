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
setup_script="$script_dir/tasks-setup.sh"
venv="${TASKS_VENV-$HOME/.local/share/tasks/venv}"
python="$venv/bin/python"
caller_cwd="$(pwd -P)"

export PYTHONPATH="$script_dir"
safe_path='import sys; cwd=sys.argv.pop(1); trusted=sys.argv.pop(1); sys.path[:]=[path for path in sys.path if path and path not in (cwd, trusted)]; sys.path.insert(0, trusted);'

runtime_ready() {
  [[ -x "$python" ]] || return 1
  "$python" -c "$safe_path import yaml, textual, tasks" "$caller_cwd" "$script_dir" >/dev/null 2>&1
}

if ! runtime_ready; then
  if [[ -t 0 ]]; then
    printf 'The tasks runtime is missing or broken. Run setup now? [y/N] '
    read -r answer || answer=
    if [[ "$answer" == [Yy]* ]]; then
      "$setup_script" || true
    fi
  fi
  if ! runtime_ready; then
    printf 'Tasks runtime is missing or broken. Run: TASKS_VENV=%q %q\n' \
      "$venv" "$setup_script" >&2
    exit 1
  fi
fi

exec "$python" -c \
  "$safe_path import runpy; runpy.run_module('tasks', run_name='__main__', alter_sys=True)" \
  "$caller_cwd" "$script_dir" "$@"
