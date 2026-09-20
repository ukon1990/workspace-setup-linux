#!/usr/bin/env bash
set -euo pipefail

pid_file="${XDG_RUNTIME_DIR:-/tmp}/wofi-app-launcher.pid"
pid=""

if [[ -r "$pid_file" ]]; then
	read -r pid <"$pid_file" || true
fi

if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
	kill "$pid"
	exit 0
fi

rm -f "$pid_file"
trap 'rm -f "$pid_file"' EXIT

wofi --show drun --allow-images --matching fuzzy --insensitive --sort-order default \
	--width 700 --height 600 --prompt Applications --define close_on_focus_loss=true \
	--define drun-display_generic=true &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
wait "$pid"
