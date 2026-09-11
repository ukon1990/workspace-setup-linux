#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT/packages"
BREW_FILE="${BREW_FILE:-$PKG_DIR/brew.txt}"
BREW_CASKS_FILE="${BREW_CASKS_FILE:-$PKG_DIR/brew-casks.txt}"
DRY_RUN="${DRY_RUN:-0}"

# Formulas required for later bootstrap steps. Failures here abort the script.
ESSENTIAL_FORMULAS=(git stow curl)

read_pkgs() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  grep -vE '^[[:space:]]*(#|$)' "$file"
}

is_essential() {
  local pkg="$1" essential
  for essential in "${ESSENTIAL_FORMULAS[@]}"; do
    if [[ "$pkg" == "$essential" ]]; then
      return 0
    fi
  done
  return 1
}

formula_installed() {
  local pkg="$1"
  brew list --formula "$pkg" >/dev/null 2>&1
}

cask_installed() {
  local pkg="$1"
  brew list --cask "$pkg" >/dev/null 2>&1
}

if ! command -v brew >/dev/null 2>&1; then
  echo 'brew is not installed. Install Homebrew first.'
  exit 1
fi

if [[ ! -f "$BREW_FILE" ]]; then
  echo "Missing brew package list: $BREW_FILE"
  exit 1
fi

formulas=()
while IFS= read -r pkg; do
  [[ -n "$pkg" ]] || continue
  formulas+=("$pkg")
done < <(read_pkgs "$BREW_FILE")

casks=()
while IFS= read -r pkg; do
  [[ -n "$pkg" ]] || continue
  casks+=("$pkg")
done < <(read_pkgs "$BREW_CASKS_FILE")

if [[ ${#formulas[@]} -eq 0 && ${#casks[@]} -eq 0 ]]; then
  echo 'No Homebrew formulas or casks listed.'
  exit 0
fi

if [[ "$DRY_RUN" == 1 ]]; then
  echo 'Dry-run: Homebrew install plan'
  if [[ ${#formulas[@]} -gt 0 ]]; then
    echo 'Formulas:'
    for pkg in "${formulas[@]}"; do
      if formula_installed "$pkg"; then
        echo "  skip (already installed): $pkg"
      else
        echo "  brew install $pkg"
      fi
    done
  fi
  if [[ ${#casks[@]} -gt 0 ]]; then
    echo 'Casks:'
    for pkg in "${casks[@]}"; do
      if cask_installed "$pkg"; then
        echo "  skip (already installed): $pkg"
      else
        echo "  brew install --cask $pkg"
      fi
    done
  fi
  exit 0
fi

installed=()
skipped=()
failed=()
failed_essential=()

install_formula() {
  local pkg="$1"
  if formula_installed "$pkg"; then
    echo "Already installed (formula): $pkg"
    skipped+=("$pkg")
    return 0
  fi

  echo "Installing formula: $pkg"
  if brew install "$pkg"; then
    installed+=("$pkg")
    return 0
  fi

  echo "Failed to install formula: $pkg"
  failed+=("$pkg")
  if is_essential "$pkg"; then
    failed_essential+=("$pkg")
  fi
  return 0
}

install_cask() {
  local pkg="$1"
  if cask_installed "$pkg"; then
    echo "Already installed (cask): $pkg"
    skipped+=("$pkg (cask)")
    return 0
  fi

  echo "Installing cask: $pkg"
  if brew install --cask "$pkg"; then
    installed+=("$pkg (cask)")
    return 0
  fi

  echo "Failed to install cask: $pkg"
  failed+=("$pkg (cask)")
  return 0
}

echo "Installing Homebrew packages from $(basename "$BREW_FILE") / $(basename "$BREW_CASKS_FILE")..."

for pkg in "${formulas[@]}"; do
  install_formula "$pkg"
done

for pkg in "${casks[@]}"; do
  install_cask "$pkg"
done

echo
echo '==> Homebrew install report'
if [[ ${#installed[@]} -gt 0 ]]; then
  echo 'Installed:'
  printf '  - %s\n' "${installed[@]}"
else
  echo 'Installed: (none)'
fi
if [[ ${#skipped[@]} -gt 0 ]]; then
  echo 'Already present (skipped):'
  printf '  - %s\n' "${skipped[@]}"
fi
if [[ ${#failed[@]} -gt 0 ]]; then
  echo 'Failed:'
  printf '  - %s\n' "${failed[@]}"
else
  echo 'Failed: (none)'
fi

if [[ ${#failed_essential[@]} -gt 0 ]]; then
  echo
  echo 'Essential Homebrew formulas failed; cannot continue reliably:'
  printf '  - %s\n' "${failed_essential[@]}"
  exit 1
fi

echo 'Homebrew package installation done.'
