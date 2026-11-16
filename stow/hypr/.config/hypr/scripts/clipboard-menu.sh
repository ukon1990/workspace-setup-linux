#!/usr/bin/env bash
# Super+C: pick an entry from the clipboard history (cliphist) and copy it again.
set -euo pipefail

if ! command -v cliphist >/dev/null 2>&1; then
	notify-send -u critical "Clipboard history" "cliphist is not installed."
	exit 1
fi

pkill -x rofi && exit 0
choice="$(cliphist list | rofi -dmenu -i -p Clipboard -theme "$HOME/.config/rofi/launcher.rasi" \
	-theme-str 'inputbar { children: [ entry ]; } textbox-hints { content: "<b>Enter</b> copy     <b>Esc</b> close"; }')" || exit 0
[[ -n "$choice" ]] && printf '%s' "$choice" | cliphist decode | wl-copy
