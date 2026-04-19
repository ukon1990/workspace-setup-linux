#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STOW_DIR="$ROOT/stow"
DRY_RUN="${DRY_RUN:-0}"

if [[ "$DRY_RUN" != 1 ]] && ! command -v stow >/dev/null 2>&1; then
  echo 'stow is not installed. Install it first.'
  exit 1
fi

mapfile -t packages < <(find "$STOW_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)

if [[ ${#packages[@]} -eq 0 ]]; then
  echo "No stow packages found in $STOW_DIR"
  exit 0
fi

echo 'Linking packages:'
printf ' - %s\n' "${packages[@]}"

if [[ "$DRY_RUN" == 1 ]]; then
  printf 'Would run: stow -d %q -t %q' "$STOW_DIR" "$HOME"
  for pkg in "${packages[@]}"; do
    printf ' %q' "$pkg"
  done
  printf '\n'
else
  stow -d "$STOW_DIR" -t "$HOME" "${packages[@]}"
  echo 'Config links updated.'
fi
