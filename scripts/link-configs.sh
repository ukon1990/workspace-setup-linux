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
echo

linked=()
skipped_conflicts=()
failed=()

stow_pkg() {
  local pkg="$1"
  local stow_args=(-d "$STOW_DIR" -t "$HOME")
  local output=""
  local status=0

  if [[ "$DRY_RUN" == 1 ]]; then
    stow_args+=(-n)
  fi

  echo "==> stow $pkg"
  set +e
  output="$(stow "${stow_args[@]}" "$pkg" 2>&1)"
  status=$?
  set -e

  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  fi

  if [[ $status -eq 0 ]]; then
    if [[ "$DRY_RUN" == 1 ]]; then
      linked+=("$pkg (dry-run ok)")
    else
      linked+=("$pkg")
    fi
    return 0
  fi

  if printf '%s\n' "$output" | grep -qi 'would cause conflicts\|existing target'; then
    echo "Skipping $pkg due to existing files (not adopting)."
    skipped_conflicts+=("$pkg")
    return 0
  fi

  echo "Failed to stow $pkg (exit $status)"
  failed+=("$pkg")
  return 0
}

for pkg in "${packages[@]}"; do
  stow_pkg "$pkg"
  echo
done

echo '==> Stow link report'
if [[ ${#linked[@]} -gt 0 ]]; then
  echo 'Linked:'
  printf '  - %s\n' "${linked[@]}"
else
  echo 'Linked: (none)'
fi
if [[ ${#skipped_conflicts[@]} -gt 0 ]]; then
  echo 'Skipped (conflicts with existing files):'
  printf '  - %s\n' "${skipped_conflicts[@]}"
  echo 'Resolve by moving/removing the real files, or restow later with: stow --adopt -d '"$STOW_DIR"' -t '"$HOME"' <pkg>'
fi
if [[ ${#failed[@]} -gt 0 ]]; then
  echo 'Failed:'
  printf '  - %s\n' "${failed[@]}"
else
  echo 'Failed: (none)'
fi

if [[ ${#failed[@]} -gt 0 ]]; then
  exit 1
fi

if [[ "$DRY_RUN" == 1 ]]; then
  echo 'Dry-run stow checks finished.'
else
  echo 'Config link pass finished.'
fi
