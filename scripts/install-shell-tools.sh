#!/usr/bin/env bash
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.config/nvm}"
SDKMAN_DIR="${SDKMAN_DIR:-$HOME/.sdkman}"
RBENV_ROOT="${RBENV_ROOT:-$HOME/.rbenv}"
NVM_VERSION="${NVM_VERSION:-v0.40.3}"
NVM_NODE_VERSION="${NVM_NODE_VERSION:-25}"
SDKMAN_JAVA_VERSION="${SDKMAN_JAVA_VERSION:-25.0.2-amzn}"
RUBY_VERSION="${RUBY_VERSION:-3.4.9}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NPM_GLOBAL_FILE="${NPM_GLOBAL_FILE:-$ROOT/packages/npm-global.txt}"
TASKS_SETUP_SCRIPT="${TASKS_SETUP_SCRIPT:-$ROOT/stow/scripts/scripts/tasks-setup.sh}"
DRY_RUN="${DRY_RUN:-0}"

# Installers must not append machine-specific setup into a Stow-owned profile.
repository_zshrc() {
  local file="${ZDOTDIR:-$HOME}/.zshrc" directory target
  [[ -L "$file" ]] || return 1
  while [[ -L "$file" ]]; do
    directory="$(cd "$(dirname "$file")" && pwd -P)" || return 1
    target="$(readlink "$file")" || return 1
    case "$target" in
      /*) file="$target" ;;
      *) file="$directory/$target" ;;
    esac
  done
  directory="$(cd "$(dirname "$file")" && pwd -P)" || return 1
  [[ "$directory/$(basename "$file")" == "$ROOT"/* ]]
}

ensure_dep() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1"
    return 1
  }
}

source_nvm() {
  if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    . "$NVM_DIR/nvm.sh"
    return 0
  fi

  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    . "$HOME/.nvm/nvm.sh"
    return 0
  fi

  echo "nvm shell scripts not found"
  return 1
}

install_nvm() {
  if [[ -s "$NVM_DIR/nvm.sh" || -s "$HOME/.nvm/nvm.sh" ]]; then
    echo "nvm already installed"
    return 0
  fi

  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would install nvm from https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh"
    return 0
  fi

  echo "Installing nvm..."
  if repository_zshrc; then export PROFILE=/dev/null; fi
  curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh" | bash
}

install_node_and_globals() {
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would install Node.js $NVM_NODE_VERSION via nvm"
    if [[ -f "$NPM_GLOBAL_FILE" ]]; then
      echo "Would install npm globals from $(basename "$NPM_GLOBAL_FILE")"
    grep -vE '^[[:space:]]*(#|$)' "$NPM_GLOBAL_FILE" | sed 's/^/  /'
    fi
    return 0
  fi

  source_nvm

  echo "Installing Node.js $NVM_NODE_VERSION via nvm..."
  nvm install "$NVM_NODE_VERSION"
  nvm alias default "$NVM_NODE_VERSION" >/dev/null
  nvm use default >/dev/null

  if [[ -f "$NPM_GLOBAL_FILE" ]]; then
    local pkg
    while IFS= read -r pkg; do
      [[ -n "$pkg" ]] || continue
      [[ "$pkg" =~ ^[[:space:]]*# ]] && continue
      if npm list -g --depth=0 "$pkg" >/dev/null 2>&1; then
        echo "npm package already installed: $pkg"
      else
        echo "Installing npm package: $pkg"
        npm install -g "$pkg"
      fi
    done < "$NPM_GLOBAL_FILE"
  fi
}

install_sdkman() {
  if [[ -d "$SDKMAN_DIR" && -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]]; then
    echo "SDKMAN already installed in $SDKMAN_DIR"
    return 0
  fi

  if [[ "$DRY_RUN" == 1 ]]; then
    echo 'Would install SDKMAN from https://get.sdkman.io'
    return 0
  fi

  echo "Installing SDKMAN..."
  if repository_zshrc; then
    SDKMAN_PROFILE_TEMP="$(mktemp -d "${TMPDIR:-/tmp}/workspace-sdkman.XXXXXX")"
    export ZDOTDIR="$SDKMAN_PROFILE_TEMP"
    trap 'rm -rf "$SDKMAN_PROFILE_TEMP"' EXIT
  fi
  curl -fsSL "https://get.sdkman.io" | "$BASH_BIN"
}

install_sdkman_java() {
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would install Java $SDKMAN_JAVA_VERSION via SDKMAN"
    return 0
  fi

  if [[ ! -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]]; then
    echo "SDKMAN init script not found at $SDKMAN_DIR/bin/sdkman-init.sh"
    return 1
  fi

  if [[ -d "$SDKMAN_DIR/candidates/java/$SDKMAN_JAVA_VERSION" ]]; then
    echo "SDKMAN Java already installed: $SDKMAN_JAVA_VERSION"
    return 0
  fi

  echo "Installing Java $SDKMAN_JAVA_VERSION via SDKMAN..."
  "$BASH_BIN" -c 'source "$1/bin/sdkman-init.sh" && sdk install java "$2"' sdkman "$SDKMAN_DIR" "$SDKMAN_JAVA_VERSION"
}

resolve_ruby_version() {
  if [[ "$RUBY_VERSION" != "latest" ]]; then
    printf '%s\n' "$RUBY_VERSION"
    return 0
  fi

  rbenv install -l | awk '/^[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+[[:space:]]*$/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); version=$0 } END { if (version != "") print version; else exit 1 }'
}

install_ruby_with_rbenv() {
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would install Ruby $RUBY_VERSION via rbenv"
    return 0
  fi

  ensure_dep rbenv

  if ! rbenv commands | grep -qx install; then
    echo 'rbenv install command is unavailable. Install ruby-build first (repo packages include it).'
    return 1
  fi

  local resolved_ruby_version
  resolved_ruby_version="$(resolve_ruby_version)"

  if [[ -d "$RBENV_ROOT/versions/$resolved_ruby_version" ]]; then
    echo "Ruby already installed via rbenv: $resolved_ruby_version"
  else
    echo "Installing Ruby $resolved_ruby_version via rbenv..."
    rbenv install "$resolved_ruby_version"
  fi

  echo "Setting global Ruby to $resolved_ruby_version"
  rbenv global "$resolved_ruby_version"
  rbenv rehash
}

install_tasks_runtime() {
  if [[ ! -x "$TASKS_SETUP_SCRIPT" ]]; then
    echo "Tasks setup script not found or not executable: $TASKS_SETUP_SCRIPT"
    return 1
  fi
  DRY_RUN="$DRY_RUN" PYTHON_BIN="$PYTHON_BIN" "$TASKS_SETUP_SCRIPT"
}

# Each installer runs in a separate Bash process so errexit remains effective,
# while a failed installer does not stop independent installations.
run_tool() {
  local label="$1" function_name="$2" existing="${3:-0}" status
  TOOL_READY=0
  if "$BASH" "$ROOT/scripts/install-shell-tools.sh" --tool "$function_name"; then
    TOOL_READY=1
    status=installed
    [[ "$existing" == 1 ]] && status='already available'
    [[ "$DRY_RUN" == 1 ]] && status=planned
  else
    status=failed
    INCOMPLETE=1
  fi
  echo "$label: $status"
}

skip_tool() {
  echo "$1: skipped ($2)"
  INCOMPLETE=1
}

main() {
  # Internal dispatch keeps installer errors isolated without disabling errexit.
  if [[ "${1:-}" == --tool ]]; then
    case "${2:-}" in
      install_nvm|install_node_and_globals|install_sdkman|install_sdkman_java|install_ruby_with_rbenv|install_tasks_runtime)
        "$2" ;;
      *) echo 'Unknown shell tool'; return 1 ;;
    esac
    return
  fi

  source "$ROOT/scripts/lib/shell-prerequisites.sh"
  prepare_shell_prerequisites
  export NVM_DIR SDKMAN_DIR RBENV_ROOT NVM_VERSION NVM_NODE_VERSION
  export SDKMAN_JAVA_VERSION RUBY_VERSION NPM_GLOBAL_FILE TASKS_SETUP_SCRIPT DRY_RUN
  INCOMPLETE=0
  local existing=0
  [[ -s "$NVM_DIR/nvm.sh" || -s "$HOME/.nvm/nvm.sh" ]] && existing=1
  if [[ "$existing" == 1 ]] || command -v curl >/dev/null 2>&1 || [[ "$DRY_RUN" == 1 ]]; then
    run_tool nvm install_nvm "$existing"
    if [[ "$TOOL_READY" == 1 ]]; then
      run_tool 'Node.js and npm globals' install_node_and_globals
    else
      skip_tool 'Node.js and npm globals' 'nvm installation failed'
    fi
  else
    skip_tool nvm 'curl unavailable'
    skip_tool 'Node.js and npm globals' 'nvm unavailable'
  fi

  if [[ "$BASH_READY" == 1 ]]; then
    existing=0
    [[ -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]] && existing=1
    if [[ "$existing" == 1 ]] || command -v curl >/dev/null 2>&1 || [[ "$DRY_RUN" == 1 ]]; then
      run_tool SDKMAN install_sdkman "$existing"
      if [[ "$TOOL_READY" == 1 ]]; then
        existing=0
        [[ -d "$SDKMAN_DIR/candidates/java/$SDKMAN_JAVA_VERSION" ]] && existing=1
        run_tool Java install_sdkman_java "$existing"
      else
        skip_tool Java 'SDKMAN installation failed'
      fi
    else
      skip_tool SDKMAN 'curl unavailable'
      skip_tool Java 'SDKMAN unavailable'
    fi
  else
    skip_tool SDKMAN 'Bash 4+ unavailable'
    skip_tool Java 'Bash 4+ unavailable'
  fi

  if [[ "$RUBY_READY" == 1 ]]; then
    existing=0
    [[ "$RUBY_VERSION" != latest && -d "$RBENV_ROOT/versions/$RUBY_VERSION" ]] && existing=1
    run_tool Ruby install_ruby_with_rbenv "$existing"
  else
    skip_tool Ruby 'rbenv or ruby-build unavailable'
  fi
  if [[ "$PYTHON_READY" == 1 ]]; then
    run_tool tasks install_tasks_runtime
    if [[ "$SHELL_OS" == Linux ]]; then
      if DRY_RUN="$DRY_RUN" PYTHON_BIN="$PYTHON_BIN" "$ROOT/stow/scripts/scripts/disks-setup.sh"; then
        echo 'disks: runtime ready'
      else
        echo 'disks: failed'
        INCOMPLETE=1
      fi
    fi
  else
    skip_tool tasks 'Python 3.12+ unavailable'
    [[ "$SHELL_OS" != Linux ]] || skip_tool disks 'Python 3.12+ unavailable'
  fi
  if ! DRY_RUN="$DRY_RUN" "$ROOT/scripts/configure-shell.sh" --profile-only; then
    echo 'Shell profile: failed'
    INCOMPLETE=1
  fi
  echo
  if [[ "$INCOMPLETE" == 1 ]]; then
    echo 'Shell tools setup incomplete; see skipped and failed tools above.'
    return 2
  fi
  echo 'Shell tools setup complete. Reload your terminal with: exec zsh -l'
}

main "$@"
