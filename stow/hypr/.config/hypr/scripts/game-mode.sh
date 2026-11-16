#!/usr/bin/env bash
# Side effects of game mode; the compositor settings live in lua/gamemode.lua.
set -euo pipefail

state_file="${XDG_RUNTIME_DIR:-/tmp}/hypr-game-mode"
widgets="$HOME/.config/waybar/scripts/status_widgets.py"

case "${1:-}" in
	on)
		: >"$state_file"
		makoctl mode -a do-not-disturb >/dev/null 2>&1 || true
		# Pause the night light and remember that it was on.
		if "$widgets" hyprsunset 2>/dev/null | grep -q '"alt": "active"'; then
			"$widgets" hyprsunset-toggle && echo night-light >"$state_file"
		fi
		;;
	off)
		[[ -e "$state_file" ]] || exit 0
		grep -q night-light "$state_file" && "$widgets" hyprsunset-toggle
		rm -f "$state_file"
		makoctl mode -r do-not-disturb >/dev/null 2>&1 || true
		;;
	*)
		echo "Usage: game-mode.sh on|off" >&2
		exit 1
		;;
esac
pkill -RTMIN+9 waybar 2>/dev/null || true
