#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT/packages"
DRY_RUN="${DRY_RUN:-0}"

# shellcheck disable=SC1091
source /etc/os-release

read_pkgs() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  grep -vE '^[[:space:]]*(#|$)' "$file"
}

show_file() {
  local title="$1" file="$2"
  if [[ -f "$file" ]]; then
    echo "==> $title ($(basename "$file"))"
    sed 's/^/  /' "$file"
  fi
}

install_pacman_file() {
  local file="$1"
  mapfile -t pkgs < <(read_pkgs "$file")
  if [[ ${#pkgs[@]} -gt 0 ]]; then
    if [[ "$DRY_RUN" == 1 ]]; then
      printf 'Would run: sudo pacman -S --needed --'
      printf ' %q' "${pkgs[@]}"
      printf '\n'
    else
      sudo pacman -S --needed -- "${pkgs[@]}"
    fi
  fi
}

install_yay_file() {
  local file="$1"
  mapfile -t pkgs < <(read_pkgs "$file")
  if [[ ${#pkgs[@]} -eq 0 ]]; then
    return 0
  fi
  if command -v yay >/dev/null 2>&1; then
    if [[ "$DRY_RUN" == 1 ]]; then
      printf 'Would run: yay -S --needed --'
      printf ' %q' "${pkgs[@]}"
      printf '\n'
    else
      yay -S --needed -- "${pkgs[@]}"
    fi
  else
    echo "Skipping AUR packages in $(basename "$file") because yay is not installed."
  fi
}

install_flatpak_file() {
  local file="$1"
  mapfile -t apps < <(read_pkgs "$file")
  if [[ ${#apps[@]} -gt 0 ]]; then
    if command -v flatpak >/dev/null 2>&1; then
      if [[ "$DRY_RUN" == 1 ]]; then
        printf 'Would run: flatpak install -y flathub'
        printf ' %q' "${apps[@]}"
        printf '\n'
      else
        flatpak install -y flathub "${apps[@]}"
      fi
    else
      echo "Skipping Flatpak apps in $(basename "$file") because flatpak is not installed."
    fi
  fi
}

install_arch() {
  install_pacman_file "$PKG_DIR/common.txt"
  install_pacman_file "$PKG_DIR/hyprland.txt"
  install_pacman_file "$PKG_DIR/apps.txt"
  install_yay_file "$PKG_DIR/aur.txt"
  install_flatpak_file "$PKG_DIR/flatpak.txt"
}

install_debian() {
  install_pacman_file "$PKG_DIR/common.txt"
  install_pacman_file "$PKG_DIR/hyprland.txt"
  install_pacman_file "$PKG_DIR/apps.txt"
  install_flatpak_file "$PKG_DIR/flatpak.txt"
}

install_fedora() {
  install_pacman_file "$PKG_DIR/common.txt"
  install_pacman_file "$PKG_DIR/hyprland.txt"
  install_pacman_file "$PKG_DIR/apps.txt"
  install_flatpak_file "$PKG_DIR/flatpak.txt"
}

case "${ID:-}" in
  arch|cachyos|manjaro|endeavouros)
    [[ "$DRY_RUN" == 1 ]] && echo 'Dry-run: Arch/CachyOS package install plan'
    install_arch
    ;;
  debian|ubuntu|linuxmint|pop|zorin)
    [[ "$DRY_RUN" == 1 ]] && echo 'Dry-run: Debian/Ubuntu package install plan'
    install_debian
    ;;
  fedora)
    [[ "$DRY_RUN" == 1 ]] && echo 'Dry-run: Fedora package install plan'
    install_fedora
    ;;
  *)
    echo "Unsupported distro: ${PRETTY_NAME:-$ID}"
    echo 'Edit scripts/install-packages.sh for your package manager.'
    exit 1
    ;;
esac

if [[ "$DRY_RUN" == 1 ]]; then
  show_file 'Package manifests' "$PKG_DIR/common.txt"
  show_file 'Hyprland packages' "$PKG_DIR/hyprland.txt"
  show_file 'Daily apps' "$PKG_DIR/apps.txt"
  show_file 'AUR packages' "$PKG_DIR/aur.txt"
  show_file 'Flatpak apps' "$PKG_DIR/flatpak.txt"
else
  echo 'Package installation done.'
fi
