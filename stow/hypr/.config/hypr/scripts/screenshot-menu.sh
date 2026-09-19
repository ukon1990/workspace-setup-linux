#!/usr/bin/env bash
# Show a small menu (Region / Full screen) and dispatch to screenshot.sh.
# Bound to the Print Screen key in lua/binds.lua.
set -euo pipefail

HYPR_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
SCREENSHOT_SCRIPT="$HYPR_DIR/scripts/screenshot.sh"

command -v wofi >/dev/null 2>&1 || {
    command -v notify-send >/dev/null 2>&1 && notify-send -u critical "Screenshot" "wofi is not installed."
    exit 1
}

CHOICE="$(printf 'Region\nFull screen' | wofi --dmenu --prompt "Screenshot" --width 250 --height 120 || true)"
CHOICE="$(printf '%s' "$CHOICE" | xargs || true)"

case "$CHOICE" in
    Region)
        exec "$SCREENSHOT_SCRIPT" region
        ;;
    "Full screen")
        exec "$SCREENSHOT_SCRIPT" full
        ;;
    *)
        # No selection (dismissed) — do nothing.
        exit 0
        ;;
esac
