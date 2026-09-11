#!/usr/bin/env bash
set -euo pipefail

DOWNLOAD_DIR="${DOWNLOAD_DIR:-$HOME/Nedlastinger}"
INSTALL_ROOT="${INSTALL_ROOT:-$HOME/.local/opt}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/.local/share/applications}"
AUTO_INSTALL="${INSTALL_APPS_AUTO:-0}"
DRY_RUN="${DRY_RUN:-0}"

JETBRAINS_IDEA_URL="https://www.jetbrains.com/idea/download/?section=linux"
JETBRAINS_RIDER_URL="https://www.jetbrains.com/rider/download/?section=linux"
CURSOR_URL="https://www.cursor.com/downloads"
GITKRAKEN_URL="https://www.gitkraken.com/download/linux-gzip"
RAIDERIO_URL="https://raider.io/addon"
ARCHON_URL="https://www.archon.gg/download?utm_source=header-cta-archon"
CURSEFORGE_URL="https://www.curseforge.com/download/app"
WARP_URL="https://www.warp.dev/download"

APP_ORDER=(warp intellij rider cursor gitkraken raiderio archon curseforge)
APP_CATEGORY_warp="System"
APP_CATEGORY_intellij="Development"
APP_CATEGORY_rider="Development"
APP_CATEGORY_cursor="Development"
APP_CATEGORY_gitkraken="Development"
APP_CATEGORY_raiderio="Gaming"
APP_CATEGORY_archon="Gaming"
APP_CATEGORY_curseforge="Gaming"
APP_DISPLAY_warp="Warp Terminal"
APP_DISPLAY_intellij="IntelliJ IDEA"
APP_DISPLAY_rider="Rider"
APP_DISPLAY_cursor="Cursor"
APP_DISPLAY_gitkraken="GitKraken"
APP_DISPLAY_raiderio="Raider.IO"
APP_DISPLAY_archon="Archon"
APP_DISPLAY_curseforge="CurseForge"
APP_REGEX_warp='^warp-terminal-.*\.pkg\.tar\.zst$'
APP_REGEX_intellij='^(idea|ideaic|ideaiu|intellij).*\.tar\.gz$'
APP_REGEX_rider='^(jetbrains\.rider|rider).*\.tar\.gz$'
APP_REGEX_cursor='^cursor.*\.(appimage|tar\.gz)$'
APP_REGEX_gitkraken='^gitkraken.*\.tar\.gz$'
APP_REGEX_raiderio='^raiderio.*\.appimage$'
APP_REGEX_archon='^archon.*\.appimage$'
APP_REGEX_curseforge='^curseforge.*\.appimage$'

print_links() {
  cat <<EOF
Download links:
- Warp:        $WARP_URL
- IntelliJ IDEA: $JETBRAINS_IDEA_URL
- Rider:        $JETBRAINS_RIDER_URL
- Cursor:       $CURSOR_URL
- GitKraken:    $GITKRAKEN_URL
- Raider.IO:    $RAIDERIO_URL
- Archon:       $ARCHON_URL
- CurseForge:   $CURSEFORGE_URL

Download the Linux archives/app images/pkg.tar.zst into: $DOWNLOAD_DIR
Then run this script again to install them.
EOF
}

find_one_regex() {
  local regex="$1"
  local file base
  while IFS= read -r file; do
    base="${file##*/}"
    if [[ "${base,,}" =~ $regex ]]; then
      printf '%s\n' "$file"
      return 0
    fi
  done < <(find "$DOWNLOAD_DIR" -maxdepth 1 -type f | sort)
  return 1
}

is_installed_warp() { command -v warp-terminal >/dev/null 2>&1 || [[ -f "$DESKTOP_DIR/warp-terminal.desktop" ]]; }
is_installed_intellij() { [[ -x "$BIN_DIR/intellij-idea" && -f "$DESKTOP_DIR/intellij-idea.desktop" ]]; }
is_installed_rider() { [[ -x "$BIN_DIR/rider" && -f "$DESKTOP_DIR/rider.desktop" ]]; }
is_installed_cursor() { [[ -x "$BIN_DIR/cursor" && -f "$DESKTOP_DIR/cursor.desktop" ]]; }
is_installed_gitkraken() { [[ -x "$BIN_DIR/gitkraken" && -f "$DESKTOP_DIR/gitkraken.desktop" ]]; }
is_installed_raiderio() { [[ -x "$BIN_DIR/raiderio" && -f "$DESKTOP_DIR/raiderio.desktop" ]]; }
is_installed_archon() { [[ -x "$BIN_DIR/archon" && -f "$DESKTOP_DIR/archon.desktop" ]]; }
is_installed_curseforge() { [[ -x "$BIN_DIR/curseforge" && -f "$DESKTOP_DIR/curseforge.desktop" ]]; }

install_warp_pkg() {
  local archive="$1"
  if [[ -t 0 && -t 1 ]]; then
    sudo pacman -U --noconfirm "$archive"
    echo "Installed Warp Terminal from $archive"
  elif sudo -n true >/dev/null 2>&1; then
    sudo -n pacman -U --noconfirm "$archive"
    echo "Installed Warp Terminal from $archive"
  else
    echo "Warp Terminal requires sudo and a terminal; skipped $archive"
  fi
}

# Invoke the repository copy so bootstrap does not depend on Stow having run.
APP_INSTALL="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../stow/scripts/scripts" && pwd)/app-install.sh"
export INSTALL_ROOT BIN_DIR DESKTOP_DIR

install_jetbrains_tarball() {
  local archive="$1" app_name="$2" launcher_name="$3" binary_name="$4" wm_class="$6" categories="$7"
  "$APP_INSTALL" "$archive" --name "$app_name" --id "$launcher_name" --subdir jetbrains \
    --exec "bin/$binary_name" --exec "bin/${binary_name}.sh" \
    --startup-class "$wm_class" --categories "$categories"
}

install_gitkraken_tarball() {
  "$APP_INSTALL" "$1" --name GitKraken --id gitkraken \
    --exec gitkraken --exec resources/bin/gitkraken.sh \
    --startup-class gitkraken --categories 'Development;IDE;'
}

install_appimage() {
  local archive="$1" app_name="$2" launcher_name="$3" wm_class="$4" categories="$5"
  local opts=()
  if [[ "${7:-0}" == 1 ]]; then
    opts+=(--preserve-launcher)
  fi
  "$APP_INSTALL" "$archive" --name "$app_name" --id "$launcher_name" \
    --startup-class "$wm_class" --categories "$categories" "${opts[@]}"
}

prompt_category() {
  local title="$1"
  shift
  local apps=("$@") opts=() app display_var desc installed

  for app in "${apps[@]}"; do
    display_var="APP_DISPLAY_${app}"
    desc="${!display_var}"
    installed=no
    case "$app" in
      warp) is_installed_warp && installed=yes ;;
      intellij) is_installed_intellij && installed=yes ;;
      rider) is_installed_rider && installed=yes ;;
      cursor) is_installed_cursor && installed=yes ;;
      gitkraken) is_installed_gitkraken && installed=yes ;;
      raiderio) is_installed_raiderio && installed=yes ;;
      archon) is_installed_archon && installed=yes ;;
      curseforge) is_installed_curseforge && installed=yes ;;
    esac
    if [[ "$installed" == yes ]]; then
      desc+=" [installed]"
    fi
    opts+=("$app" "$desc" ON)
  done

  if [[ "$AUTO_INSTALL" == 1 || ! -t 0 || ! -t 1 || ! -x "$(command -v whiptail 2>/dev/null)" ]]; then
    printf '%s\n' "${apps[@]}"
    return 0
  fi

  whiptail --title "$title" --checklist "Select apps to install/reinstall. Use SPACE to toggle." 20 100 12 \
    "${opts[@]}" 3>&1 1>&2 2>&3 || return 1
}

parse_whiptail_output() {
  local raw="$1" cleaned
  cleaned="${raw//\"/}"
  # shellcheck disable=SC2206
  printf '%s\n' $cleaned
}

main() {
  case "${1:-}" in
    --list|-l)
      print_links
      exit 0
      ;;
    --yes|--all)
      AUTO_INSTALL=1
      ;;
    --dry-run)
      DRY_RUN=1
      AUTO_INSTALL=1
      ;;
  esac

  [[ -d "$DOWNLOAD_DIR" ]] || { echo "Download directory not found: $DOWNLOAD_DIR"; print_links; exit 1; }

  local selected selected_dev selected_games raw_dev raw_games
  raw_dev="$(prompt_category "System + Development apps" warp intellij rider cursor gitkraken)"
  raw_games="$(prompt_category "Gaming apps" raiderio archon curseforge)"
  mapfile -t selected_dev < <(parse_whiptail_output "$raw_dev")
  mapfile -t selected_games < <(parse_whiptail_output "$raw_games")
  selected=("${selected_dev[@]}" "${selected_games[@]}")

  if [[ "$DRY_RUN" == 1 ]]; then
    echo 'Dry-run: no files will be installed or modified.'
    echo 'Would process these apps:'
    printf ' - %s\n' "${selected[@]}"
    for app in "${selected[@]}"; do
      case "$app" in
        warp) archive="$(find_one_regex "$APP_REGEX_warp" || true)" ;;
        intellij) archive="$(find_one_regex "$APP_REGEX_intellij" || true)" ;;
        rider) archive="$(find_one_regex "$APP_REGEX_rider" || true)" ;;
        cursor) archive="$(find_one_regex "$APP_REGEX_cursor" || true)" ;;
        gitkraken) archive="$(find_one_regex "$APP_REGEX_gitkraken" || true)" ;;
        raiderio) archive="$(find_one_regex "$APP_REGEX_raiderio" || true)" ;;
        archon) archive="$(find_one_regex "$APP_REGEX_archon" || true)" ;;
        curseforge) archive="$(find_one_regex "$APP_REGEX_curseforge" || true)" ;;
      esac
      if [[ -n "${archive:-}" ]]; then
        echo "Would install $app from: $archive"
      else
        echo "Would skip $app (archive not found in $DOWNLOAD_DIR)"
      fi
      unset archive
    done
    exit 0
  fi

  local app archive installed
  for app in "${selected[@]}"; do
    case "$app" in
      warp)
        archive="$(find_one_regex "$APP_REGEX_warp" || true)"
        if [[ -n "$archive" ]]; then
          install_warp_pkg "$archive"
        else
          installed="$(is_installed_warp && echo yes || echo no)"
          echo "Warp pkg not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      intellij)
        archive="$(find_one_regex "$APP_REGEX_intellij" || true)"
        if [[ -n "$archive" ]]; then
          install_jetbrains_tarball "$archive" "IntelliJ IDEA" intellij-idea idea idea.png jetbrains-idea "Development;IDE;"
        else
          installed="$(is_installed_intellij && echo yes || echo no)"
          echo "IntelliJ IDEA archive not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      rider)
        archive="$(find_one_regex "$APP_REGEX_rider" || true)"
        if [[ -n "$archive" ]]; then
          install_jetbrains_tarball "$archive" "Rider" rider rider rider.png jetbrains-rider "Development;IDE;"
        else
          installed="$(is_installed_rider && echo yes || echo no)"
          echo "Rider archive not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      cursor)
        archive="$(find_one_regex "$APP_REGEX_cursor" || true)"
        if [[ -n "$archive" ]]; then
          if [[ "${archive,,}" == *.appimage ]]; then
            install_appimage "$archive" "Cursor" cursor Cursor "Development;IDE;" cursor 1
          else
            "$APP_INSTALL" "$archive" --name Cursor --id cursor --exec cursor --exec bin/cursor \
              --startup-class Cursor --categories "Development;IDE;"
          fi
        else
          installed="$(is_installed_cursor && echo yes || echo no)"
          echo "Cursor archive not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      gitkraken)
        archive="$(find_one_regex "$APP_REGEX_gitkraken" || true)"
        if [[ -n "$archive" ]]; then
          install_gitkraken_tarball "$archive"
        else
          installed="$(is_installed_gitkraken && echo yes || echo no)"
          echo "GitKraken archive not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      raiderio)
        archive="$(find_one_regex "$APP_REGEX_raiderio" || true)"
        if [[ -n "$archive" ]]; then
          install_appimage "$archive" "Raider.IO" raiderio RaiderIO "Game;Utility;" raiderio
        else
          installed="$(is_installed_raiderio && echo yes || echo no)"
          echo "Raider.IO AppImage not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      archon)
        archive="$(find_one_regex "$APP_REGEX_archon" || true)"
        if [[ -n "$archive" ]]; then
          install_appimage "$archive" "Archon" archon Archon "Game;Utility;" archon
        else
          installed="$(is_installed_archon && echo yes || echo no)"
          echo "Archon AppImage not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
      curseforge)
        archive="$(find_one_regex "$APP_REGEX_curseforge" || true)"
        if [[ -n "$archive" ]]; then
          install_appimage "$archive" "CurseForge" curseforge CurseForge "Game;Utility;" curseforge
        else
          installed="$(is_installed_curseforge && echo yes || echo no)"
          echo "CurseForge AppImage not found in $DOWNLOAD_DIR${installed:+ (already installed: $installed)}"
        fi
        ;;
    esac
  done

  echo
  echo "Done. Desktop launchers were written to: $DESKTOP_DIR"
}

main "$@"
