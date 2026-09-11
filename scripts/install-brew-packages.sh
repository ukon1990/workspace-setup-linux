#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT/packages"
BREW_FILE="${BREW_FILE:-$PKG_DIR/brew.txt}"
DRY_RUN="${DRY_RUN:-0}"

read_pkgs() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  grep -vE '^[[:space:]]*(#|$)' "$file"
}

if ! command -v brew >/dev/null 2>&1; then
  echo 'brew is not installed. Install Homebrew first.'
  exit 1
fi

if [[ ! -f "$BREW_FILE" ]]; then
  echo "Missing brew package list: $BREW_FILE"
  exit 1
fi

pkgs=()
while IFS= read -r pkg; do
  [[ -n "$pkg" ]] || continue
  pkgs+=("$pkg")
done < <(read_pkgs "$BREW_FILE")

if [[ ${#pkgs[@]} -eq 0 ]]; then
  echo "No packages listed in $BREW_FILE"
  exit 0
fi

if [[ "$DRY_RUN" == 1 ]]; then
  echo 'Dry-run: Homebrew formula install plan'
  printf 'Would run: brew install'
  printf ' %q' "${pkgs[@]}"
  printf '\n'
  echo '==> Brew formulas (brew.txt)'
  sed 's/^/  /' "$BREW_FILE"
  exit 0
fi

echo "Installing Homebrew formulas from $(basename "$BREW_FILE")..."
brew install "${pkgs[@]}"
echo 'Homebrew package installation done.'
