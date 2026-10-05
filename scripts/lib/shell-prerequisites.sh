#!/usr/bin/env bash
# Shared preflight; compatible with the Bash 3.2 shipped by macOS.

compatible_bash() {
  "$1" -c '(( BASH_VERSINFO[0] >= 4 ))' >/dev/null 2>&1
}

compatible_python() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' >/dev/null 2>&1
}

resolve_executable() {
  local executable
  executable="$(command -v "$1")" || return 1
  [[ -x "$executable" ]] || return 1
  if [[ "$executable" != /* ]]; then
    executable="$(cd "$(dirname "$executable")" && pwd)/$(basename "$executable")"
  fi
  printf '%s\n' "$executable"
}

find_homebrew() {
  BREW_BIN="$(resolve_executable brew)" || BREW_BIN=""
  if [[ -z "$BREW_BIN" ]]; then
    local candidate
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [[ -x "$candidate" ]]; then BREW_BIN="$candidate"; break; fi
    done
  fi
  [[ -n "$BREW_BIN" ]] || return 1
  local environment
  environment="$("$BREW_BIN" shellenv)" || return 1
  eval "$environment"
  hash -r
}

repair_formula() {
  local formula="$1" action=install
  [[ -n "${BREW_BIN:-}" ]] || return 1
  if "$BREW_BIN" list --versions "$formula" >/dev/null 2>&1; then action=upgrade; fi
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would $action Homebrew prerequisite: $formula"
    return 0
  fi
  echo "Homebrew prerequisite: $action $formula"
  "$BREW_BIN" "$action" "$formula" || return 1
  hash -r
}

prepare_versioned_dependency() {
  local variable="$1" command_name="$2" formula="$3" validator="$4"
  local explicit="$5" selected="${!variable}" candidate prefix
  if [[ "$explicit" == 1 ]]; then
    candidate="$(resolve_executable "$selected")" || candidate=""
    if [[ -n "$candidate" ]] && "$validator" "$candidate"; then
      printf -v "$variable" '%s' "$candidate"
      return 0
    fi
    echo "Invalid explicit $variable: $selected (does not meet the required version)"
    return 1
  fi
  candidate="$(resolve_executable "$command_name")" || candidate=""
  if [[ -n "$candidate" ]] && "$validator" "$candidate"; then
    printf -v "$variable" '%s' "$candidate"
    return 0
  fi
  if [[ "$SHELL_OS" == Darwin && -n "${BREW_BIN:-}" ]]; then
    prefix="$("$BREW_BIN" --prefix "$formula" 2>/dev/null)" || prefix=""
    candidate="$(formula_executable "$prefix" "$command_name" "$validator")" || candidate=""
    if [[ -z "$candidate" ]]; then
      repair_formula "$formula" || return 1
      [[ "$DRY_RUN" == 1 ]] && return 0
      prefix="$("$BREW_BIN" --prefix "$formula")" || return 1
      candidate="$(formula_executable "$prefix" "$command_name" "$validator")" || candidate=""
    fi
    if [[ -n "$candidate" ]]; then
      printf -v "$variable" '%s' "$candidate"
      return 0
    fi
  fi
  echo "Missing compatible $command_name prerequisite ($formula)"
  return 1
}

formula_executable() {
  local prefix="$1" command_name="$2" validator="$3" candidate
  # Versioned Python formulae expose python3 in libexec/bin on some releases.
  for candidate in "$prefix/bin/$command_name" "$prefix/libexec/bin/$command_name"; do
    if [[ -x "$candidate" ]] && "$validator" "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  candidate="$(resolve_executable "$command_name")" || return 1
  "$validator" "$candidate" || return 1
  printf '%s\n' "$candidate"
}

prepare_shell_prerequisites() {
  SHELL_OS="$(uname -s)"
  BASH_READY=0 PYTHON_READY=0 RUBY_READY=0
  local bash_explicit=0 python_explicit=0
  [[ "${BASH_BIN+x}" ]] && bash_explicit=1
  [[ "${PYTHON_BIN+x}" ]] && python_explicit=1
  BASH_BIN="${BASH_BIN-bash}" PYTHON_BIN="${PYTHON_BIN-python3}"
  BREW_BIN=""
  if [[ "$SHELL_OS" == Darwin ]]; then
    find_homebrew || echo 'Homebrew unavailable; checking existing dependencies.'
  fi
  if prepare_versioned_dependency BASH_BIN bash bash compatible_bash "$bash_explicit"; then BASH_READY=1; fi
  if prepare_versioned_dependency PYTHON_BIN python3 python compatible_python "$python_explicit"; then PYTHON_READY=1; fi
  if [[ "$SHELL_OS" == Darwin ]] && ! command -v rbenv >/dev/null 2>&1; then
    repair_formula rbenv || true
  fi
  if command -v rbenv >/dev/null 2>&1 && rbenv commands | grep -qx install; then
    RUBY_READY=1
  elif [[ "$SHELL_OS" == Darwin ]] && repair_formula ruby-build; then
    if [[ "$DRY_RUN" == 1 ]] || { command -v rbenv >/dev/null 2>&1 && rbenv commands | grep -qx install; }; then
      RUBY_READY=1
    fi
  fi
  export BASH_BIN PYTHON_BIN
}
