#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_PACKAGES=0
RUN_SHELL=0
RUN_LINK=0
RUN_APPS=0
AUTO_YES=0
DRY_RUN=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

macOS bootstrap (also reachable via ./bootstrap.sh).

Options:
  --packages   Install Homebrew formulas from packages/brew.txt (+ Ollama cask)
  --shell      Install shell tools (nvm -> Node 25 -> npm globals -> SDKMAN -> Java 25.0.2-amzn -> rbenv Ruby)
  --link       Link shared configs into your home directory
  --apps       Skipped on macOS (Linux vendor apps only)
  --yes        Run selected steps non-interactively; implies --packages --shell --link
  --all        Same as --yes
  --dry-run    Show what would run without changing anything
  -h, --help   Show this help
EOF
}

run_step() {
  local title="$1"
  shift
  echo
  echo "==> $title"
  if [[ $DRY_RUN -eq 1 ]]; then
    DRY_RUN=1 "$@"
  else
    "$@"
  fi
}

ask_yes_no() {
  local prompt="$1" answer lowered
  if [[ $DRY_RUN -eq 1 ]]; then
    return 0
  fi
  read -r -p "$prompt [y/N] " answer
  lowered="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
  [[ "$lowered" == y* ]]
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi

  if [[ $DRY_RUN -eq 1 ]]; then
    echo 'Would install Homebrew from https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh'
    return 0
  fi

  echo 'Installing Homebrew...'
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi

  if ! command -v brew >/dev/null 2>&1; then
    echo 'Homebrew installed but brew is not on PATH. Open a new shell or add brew to PATH, then re-run.'
    exit 1
  fi
}

install_base_tools() {
  ensure_homebrew
  if [[ $DRY_RUN -eq 1 ]]; then
    echo 'Would install base tools via brew: git stow curl'
    return 0
  fi
  brew install git stow curl
}

install_ollama() {
  ensure_homebrew
  if [[ $DRY_RUN -eq 1 ]]; then
    echo 'Would install Ollama via: brew install --cask ollama'
    return 0
  fi
  if brew list --cask ollama >/dev/null 2>&1; then
    echo 'Ollama cask already installed'
    return 0
  fi
  brew install --cask ollama
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --packages) RUN_PACKAGES=1 ;;
    --shell) RUN_SHELL=1 ;;
    --link) RUN_LINK=1 ;;
    --apps) RUN_APPS=1 ;;
    --yes|--all)
      AUTO_YES=1
      RUN_PACKAGES=1
      RUN_SHELL=1
      RUN_LINK=1
      ;;
    --dry-run)
      DRY_RUN=1
      AUTO_YES=1
      RUN_PACKAGES=1
      RUN_SHELL=1
      RUN_LINK=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

printf '\n== dotfiles bootstrap (macOS) ==\n'
printf 'Repo: %s\n' "$ROOT"
if [[ $DRY_RUN -eq 1 ]]; then
  echo 'Mode: dry-run'
fi

# Prefer Homebrew's brew on PATH for Apple Silicon / Intel.
if [[ -x /opt/homebrew/bin/brew ]] && ! command -v brew >/dev/null 2>&1; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]] && ! command -v brew >/dev/null 2>&1; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

if ! command -v git >/dev/null 2>&1 || ! command -v stow >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  echo 'Installing base tools...'
  install_base_tools
fi

if [[ $RUN_PACKAGES -eq 0 && $RUN_SHELL -eq 0 && $RUN_LINK -eq 0 ]]; then
  RUN_PACKAGES=1
  RUN_SHELL=1
  RUN_LINK=1
fi

if [[ $RUN_PACKAGES -eq 1 ]]; then
  if [[ $AUTO_YES -eq 1 ]] || ask_yes_no 'Install Homebrew packages now (brew.txt + Ollama cask)?'; then
    ensure_homebrew
    run_step 'Installing Homebrew packages' env DRY_RUN="$DRY_RUN" "$ROOT/scripts/install-brew-packages.sh"
    run_step 'Installing Ollama' install_ollama
  fi
fi

if [[ $RUN_SHELL -eq 1 ]]; then
  if [[ $AUTO_YES -eq 1 ]] || ask_yes_no 'Install shell tools now (nvm -> Node 25 -> npm globals -> SDKMAN -> Java 25.0.2-amzn -> rbenv Ruby)?'; then
    run_step 'Installing shell tools' env DRY_RUN="$DRY_RUN" "$ROOT/scripts/install-shell-tools.sh"
  fi
fi

if [[ $RUN_LINK -eq 1 ]]; then
  run_step 'Linking shared configs into your home directory' env DRY_RUN="$DRY_RUN" "$ROOT/scripts/link-configs.sh"
fi

if [[ $RUN_APPS -eq 1 ]]; then
  echo
  echo 'Skipping --apps on macOS (vendor app installer is Linux-only).'
fi

echo
echo 'Done.'
