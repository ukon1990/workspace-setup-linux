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

Options:
  --packages   Install repo packages (common -> Hyprland -> apps -> AUR)
  --shell      Install shell tools (nvm -> Node 25 -> npm globals -> SDKMAN -> Java 25.0.2-amzn -> rbenv Ruby)
  --link       Link configs into your home directory
  --apps       Install downloaded vendor apps
  --yes        Run selected steps non-interactively; implies --packages --shell --link --apps
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
  local prompt="$1" answer
  if [[ $DRY_RUN -eq 1 ]]; then
    return 0
  fi
  read -r -p "$prompt [y/N] " answer
  [[ "${answer,,}" == y* ]]
}

install_base_tools() {
  case "${ID:-}" in
    arch|cachyos|manjaro|endeavouros)
      if [[ $DRY_RUN -eq 1 ]]; then
        echo 'Would install base tools: git stow curl'
      else
        sudo pacman -S --needed git stow curl
      fi
      ;;
    debian|ubuntu|linuxmint|pop|zorin)
      if [[ $DRY_RUN -eq 1 ]]; then
        echo 'Would install base tools: git stow curl'
      else
        sudo apt update
        sudo apt install -y git stow curl
      fi
      ;;
    fedora)
      if [[ $DRY_RUN -eq 1 ]]; then
        echo 'Would install base tools: git stow curl'
      else
        sudo dnf install -y git stow curl
      fi
      ;;
    *)
      echo "Unsupported distro: ${PRETTY_NAME:-$ID}"
      echo 'Install at least: git, stow, curl'
      return 1
      ;;
  esac
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
      RUN_APPS=1
      ;;
    --dry-run)
      DRY_RUN=1
      AUTO_YES=1
      RUN_PACKAGES=1
      RUN_SHELL=1
      RUN_LINK=1
      RUN_APPS=1
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

printf '\n== dotfiles bootstrap ==\n'
printf 'Repo: %s\n' "$ROOT"
if [[ $DRY_RUN -eq 1 ]]; then
  echo 'Mode: dry-run'
fi

if [[ ! -f /etc/os-release ]]; then
  echo 'Cannot detect operating system (/etc/os-release missing).'
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release

if ! command -v git >/dev/null 2>&1 || ! command -v stow >/dev/null 2>&1; then
  echo 'Installing base tools...'
  install_base_tools
fi

if [[ $RUN_PACKAGES -eq 0 && $RUN_SHELL -eq 0 && $RUN_LINK -eq 0 && $RUN_APPS -eq 0 ]]; then
  RUN_PACKAGES=1
  RUN_SHELL=1
  RUN_LINK=1
  RUN_APPS=1
fi

if [[ $RUN_PACKAGES -eq 1 ]]; then
  if [[ $AUTO_YES -eq 1 ]] || ask_yes_no 'Install repo packages now (common -> Hyprland -> apps -> AUR)?'; then
    run_step 'Installing repo packages' "$ROOT/scripts/install-packages.sh"
  fi
fi

if [[ $RUN_SHELL -eq 1 ]]; then
  if [[ $AUTO_YES -eq 1 ]] || ask_yes_no 'Install shell tools now (nvm -> Node 25 -> npm globals -> SDKMAN -> Java 25.0.2-amzn -> rbenv Ruby)?'; then
    run_step 'Installing shell tools' "$ROOT/scripts/install-shell-tools.sh"
  fi
fi

if [[ $RUN_LINK -eq 1 ]]; then
  run_step 'Linking configs into your home directory' "$ROOT/scripts/link-configs.sh"
fi

if [[ $RUN_APPS -eq 1 ]]; then
  if [[ $AUTO_YES -eq 1 ]] || ask_yes_no 'Install downloaded vendor apps now (Warp / JetBrains / Cursor / GitKraken / gaming apps)?'; then
    if [[ $AUTO_YES -eq 1 ]]; then
      run_step 'Installing downloaded vendor apps' env INSTALL_APPS_AUTO=1 DRY_RUN="$DRY_RUN" "$ROOT/scripts/install-apps.sh" --yes
    else
      run_step 'Installing downloaded vendor apps' env DRY_RUN="$DRY_RUN" "$ROOT/scripts/install-apps.sh"
    fi
  else
    echo
    echo "Tip: run '$ROOT/scripts/install-apps.sh --list' to get download links."
  fi
fi

echo
echo 'Done.'
