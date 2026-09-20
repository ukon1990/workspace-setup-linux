#!/usr/bin/env bash
set -euo pipefail

notify() {
	local urgency="${2:-normal}"
	if command -v notify-send >/dev/null 2>&1; then
		notify-send -u "$urgency" "Hotkeys" "$1" || true
	fi
}

fail() {
	notify "$1" critical
	printf 'hotkey-menu: %s\n' "$1" >&2
	exit 1
}

command -v wofi >/dev/null 2>&1 || fail "wofi is not installed."
command -v jq >/dev/null 2>&1 || fail "jq is not installed."
command -v hyprctl >/dev/null 2>&1 || fail "hyprctl is not installed."

binds="$(hyprctl binds -j 2>/dev/null)" || fail "Could not read active Hyprland shortcuts."
map_file="$(mktemp)"
menu_file="$(mktemp)"
trap 'rm -f "$map_file" "$menu_file"' EXIT

if ! printf '%s' "$binds" | jq -j '
	def hasmod($bit): ((.modmask / $bit | floor) % 2) == 1;
	def key_label:
		if . == "mouse_down" then "Scroll down"
		elif . == "mouse_up" then "Scroll up"
		elif . == "mouse:272" then "Left mouse button"
		elif . == "mouse:273" then "Right mouse button"
		else .
		end;
	def chord:
		([
			if hasmod(64) then "SUPER" else empty end,
			if hasmod(1) then "SHIFT" else empty end,
			if hasmod(4) then "CTRL" else empty end,
			if hasmod(8) then "ALT" else empty end
		] + [(.key | key_label)]) | join(" + ");

	.[] |
	select(.has_description and .description != "") |
	(if .mouse then "reference:" else "run:" end) +
	"\(.modmask):\(.key)\t\(chord)  \(.description)\n"
' >"$map_file"; then
	fail "Could not format active Hyprland shortcuts."
fi

cut -f2- "$map_file" >"$menu_file"
[[ -s "$menu_file" ]] || fail "No described Hyprland shortcuts were found."

selection="$(
	wofi \
		--dmenu \
		--prompt "Hotkeys" \
		--matching fuzzy \
		--insensitive \
		--width 700 \
		--height 600 \
		<"$menu_file" || true
)"
[[ -n "$selection" ]] || exit 0

choice="$(awk -F '\t' -v selection="$selection" '$2 == selection { print $1; exit }' "$map_file")"
[[ -n "$choice" ]] || fail "Wofi returned an unknown shortcut."

case "$choice" in
	reference:*)
		notify "This pointer gesture is reference-only."
		;;
	run:*)
		id="${choice#run:}"
		[[ "$id" =~ ^[0-9]+:[A-Za-z0-9_:.-]+$ ]] || fail "Wofi returned an invalid shortcut."
		hyprctl dispatch "function() require(\"lua.hotkeys\").execute(\"$id\") end" >/dev/null ||
			fail "Could not execute the selected shortcut."
		;;
esac
