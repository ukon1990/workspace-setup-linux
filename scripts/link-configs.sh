#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STOW_DIR="$ROOT/stow"
PKG_DIR="$ROOT/packages"
DRY_RUN="${DRY_RUN:-0}"

read_list() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  grep -vE '^[[:space:]]*(#|$)' "$file"
}

os_name="$(uname -s)"
packages=()

while IFS= read -r pkg; do
  [[ -n "$pkg" ]] || continue
  packages+=("$pkg")
done < <(read_list "$PKG_DIR/stow-shared.txt")

case "$os_name" in
  Linux)
    while IFS= read -r pkg; do
      [[ -n "$pkg" ]] || continue
      packages+=("$pkg")
    done < <(read_list "$PKG_DIR/stow-linux.txt")
    ;;
  Darwin)
    ;;
  *)
    echo "Unsupported operating system for linking: $os_name"
    exit 1
    ;;
esac

if [[ ${#packages[@]} -eq 0 ]]; then
  echo "No stow packages selected for $os_name"
  exit 0
fi

missing=()
for pkg in "${packages[@]}"; do
  if [[ ! -d "$STOW_DIR/$pkg" ]]; then
    missing+=("$pkg")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo 'Missing stow package directories:'
  printf ' - %s\n' "${missing[@]}"
  exit 1
fi

if [[ "$DRY_RUN" != 1 ]] && ! command -v stow >/dev/null 2>&1; then
  echo 'stow is not installed. Install it first.'
  exit 1
fi

echo "Linking packages for $os_name:"
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
