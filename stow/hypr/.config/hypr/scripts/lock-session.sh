#!/usr/bin/env bash
# Lock the current graphical session (apps keep running underneath).
set -eu

HYPR_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
HYPRLOCK_CONF="$HYPR_DIR/hyprlock.conf"

notify_fail() {
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -u critical "Lock failed" "$1"
    else
        printf '%s\n' "$1" >&2
    fi
    exit 1
}

if pgrep -x hyprlock >/dev/null 2>&1; then
    exit 0
fi

if command -v hyprlock >/dev/null 2>&1 && [[ -f "$HYPRLOCK_CONF" ]]; then
    exec hyprlock
fi

if command -v swaylock >/dev/null 2>&1; then
    exec swaylock
fi

notify_fail "Install hyprlock (with ~/.config/hypr/hyprlock.conf) or swaylock."
