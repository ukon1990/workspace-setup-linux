#!/usr/bin/env bash
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.config/nvm}"
SDKMAN_DIR="${SDKMAN_DIR:-$HOME/.sdkman}"
NVM_VERSION="${NVM_VERSION:-v0.40.3}"
NVM_NODE_VERSION="${NVM_NODE_VERSION:-25}"
SDKMAN_JAVA_VERSION="${SDKMAN_JAVA_VERSION:-25.0.2-amzn}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NPM_GLOBAL_FILE="${NPM_GLOBAL_FILE:-$ROOT/packages/npm-global.txt}"
DRY_RUN="${DRY_RUN:-0}"

ensure_dep() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1"
    exit 1
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
  exit 1
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
  curl -s "https://get.sdkman.io" | bash
}

install_sdkman_java() {
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would install Java $SDKMAN_JAVA_VERSION via SDKMAN"
    return 0
  fi

  if [[ ! -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]]; then
    echo "SDKMAN init script not found at $SDKMAN_DIR/bin/sdkman-init.sh"
    exit 1
  fi

  if [[ -d "$SDKMAN_DIR/candidates/java/$SDKMAN_JAVA_VERSION" ]]; then
    echo "SDKMAN Java already installed: $SDKMAN_JAVA_VERSION"
    return 0
  fi

  echo "Installing Java $SDKMAN_JAVA_VERSION via SDKMAN..."
  bash -lc "source \"$SDKMAN_DIR/bin/sdkman-init.sh\" && sdk install java $SDKMAN_JAVA_VERSION"
}

main() {
  ensure_dep curl
  ensure_dep bash

  install_nvm
  install_node_and_globals
  install_sdkman
  install_sdkman_java

  echo
  echo "Shell tools installed. Restart your shell or source the init scripts."
  echo "nvm:    ${NVM_DIR}"
  echo "Node:   ${NVM_NODE_VERSION}"
  echo "SDKMAN: $SDKMAN_DIR"
  echo "Java:   ${SDKMAN_JAVA_VERSION}"
}

main "$@"
