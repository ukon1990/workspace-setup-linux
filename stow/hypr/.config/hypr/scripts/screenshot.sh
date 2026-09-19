#!/usr/bin/env bash
# Capture a screenshot (full screen or a user-selected region), save it,
# copy it to the clipboard, notify the user, then open it in swappy for
# optional annotation.
#
# Usage: screenshot.sh full|region
set -euo pipefail

MODE="${1:-}"
SAVE_DIR="${XDG_PICTURES_DIR:-$HOME/Pictures}/Screenshots"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$SAVE_DIR/screenshot-$TIMESTAMP.png"

notify() {
    command -v notify-send >/dev/null 2>&1 && notify-send "$@" || true
}

notify_fail() {
    notify -u critical "Screenshot failed" "$1"
    printf '%s\n' "$1" >&2
    exit 1
}

command -v grim >/dev/null 2>&1 || notify_fail "grim is not installed."
command -v wl-copy >/dev/null 2>&1 || notify_fail "wl-copy (wl-clipboard) is not installed."

mkdir -p "$SAVE_DIR"

case "$MODE" in
    full)
        grim "$FILE"
        ;;
    region)
        command -v slurp >/dev/null 2>&1 || notify_fail "slurp is not installed."
        GEOMETRY="$(slurp || true)"
        # Empty selection means the user cancelled (e.g. pressed Escape).
        [[ -z "$GEOMETRY" ]] && exit 0
        grim -g "$GEOMETRY" "$FILE"
        ;;
    *)
        printf 'Usage: %s full|region\n' "$0" >&2
        exit 1
        ;;
esac

[[ -f "$FILE" ]] || notify_fail "Screenshot capture failed."

wl-copy < "$FILE"
notify "Screenshot saved" "$FILE" -i "$FILE"

if command -v swappy >/dev/null 2>&1; then
    swappy -f "$FILE" &
fi
