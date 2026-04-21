#!/usr/bin/env bash
set -euo pipefail

load_session_env() {
    local pid="$1"
    [[ -n "$pid" && -r "/proc/$pid/environ" ]] || return 1

    while IFS= read -r -d '' entry; do
        case "${entry%%=*}" in
            DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR|HYPRLAND_INSTANCE_SIGNATURE|DBUS_SESSION_BUS_ADDRESS|XDG_CURRENT_DESKTOP|XDG_SESSION_TYPE)
                export "$entry"
                ;;
        esac
    done <"/proc/$pid/environ"
}

fallback_runtime_env() {
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

    if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
        local socket
        socket="$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name 'wayland-*' -printf '%f\n' 2>/dev/null | sort | head -n 1)"
        [[ -n "$socket" ]] && export WAYLAND_DISPLAY="$socket"
    fi

    if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" && -d "$XDG_RUNTIME_DIR/hypr" ]]; then
        local signature
        signature="$(find "$XDG_RUNTIME_DIR/hypr" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort | tail -n 1)"
        [[ -n "$signature" ]] && export HYPRLAND_INSTANCE_SIGNATURE="$signature"
    fi
}

if [[ -z "${WAYLAND_DISPLAY:-}" || -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    load_session_env "$(pgrep -xo Hyprland || true)" || true
fi

fallback_runtime_env

if [[ -z "${WAYLAND_DISPLAY:-}" || -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    echo "Could not determine Hyprland session environment." >&2
    exit 1
fi

pkill -x waybar || true
nohup waybar >/dev/null 2>&1 &

echo "Waybar reloaded."
