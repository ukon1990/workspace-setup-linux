#!/usr/bin/env bash
# Start Waybar with the config that fits the main monitor's current width.
# --if-changed keeps a bar that already runs with the right config.
set -euo pipefail

# Several Hyprland events can ask at once; let one caller decide at a time.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/waybar-launch.lock"
flock 9

main="${MAIN_MONITOR:-DP-1}"
width="$(hyprctl monitors -j | jq -r --arg m "$main" '.[] | select(.name == $m) | .width')"
config="$HOME/.config/waybar/config.jsonc"
((${width:-0} >= 5120)) && config="$HOME/.config/waybar/config-wide.jsonc"

if [[ "${1:-}" == "--if-changed" ]] && pgrep -fx "waybar -c $config" >/dev/null; then
	exit 0
fi

pkill -x waybar || true
waybar -c "$config" 9>&- >/dev/null 2>&1 &
disown
