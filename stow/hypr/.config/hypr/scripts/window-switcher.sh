#!/usr/bin/env bash
# Super+Tab window switcher, most recently used first.
# Hyprland owns the keys (see the "switcher" submap in lua/binds.lua): hold
# Super, tap Tab to move, release Super to switch. Rofi only draws the cards.
set -euo pipefail

state="${XDG_RUNTIME_DIR:-/tmp}/hypr-switcher"
mkdir -p "$state"
exec 9>"$state/lock"
flock 9 # start/next/commit arrive as separate processes; run them in order

# Icon and display name per window class, read from the matching .desktop entry.
desktop_field() { sed -n "s/^$1=//p" "$2" | head -n1; }
entry_for() {
	local class="$1" file="" dir
	for dir in "$HOME/.local/share/applications" /usr/share/applications; do
		[[ -f "$dir/$class.desktop" ]] && file="$dir/$class.desktop" && break
		file="$(grep -lsiE "^StartupWMClass=${class//./\\.}\$" "$dir"/*.desktop | head -n1)" && [[ -n "$file" ]] && break
	done
	[[ -n "$file" ]] || return 0
	jq -cn --arg icon "$(desktop_field Icon "$file")" --arg name "$(desktop_field Name "$file")" '{$icon, $name}'
}

# Snapshot the open windows and render one card per window:
# "App\ntitle\nws N · tab i/n" plus the icon.
snapshot() {
	local clients entries="{}" class entry
	clients="$(hyprctl clients -j | jq -c '[.[] | select(.mapped and (.workspace.id != -99))] | sort_by(.focusHistoryID)')"
	while read -r class; do
		entry="$(entry_for "$class")"
		entries="$(jq -c --arg c "$class" --argjson e "${entry:-null}" '. + {($c): $e}' <<<"$entries")"
	done < <(jq -r '[.[].class] | unique[]' <<<"$clients")

	printf '%s' "$clients" >"$state/clients.json"
	jq -r --argjson entries "$entries" '
		def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
		def tab: .address as $a | (.grouped | length) as $n
			| if $n > 1 then " · tab \((.grouped | index($a)) + 1)/\($n)" else "" end;
		.[] |
		"<b>\(($entries[.class].name // .title)[0:22] | esc)</b>&#10;" +
		"<span size=\"small\" alpha=\"70%\">\(.title[0:26] | esc)</span>&#10;" +
		"<span size=\"x-small\" alpha=\"70%\">ws \(.workspace.name | esc)\(tab)</span>" +
		"\u0000icon\u001f\($entries[.class].icon // "application-x-executable")"
	' <<<"$clients" >"$state/rows"
}

count() { jq 'length' "$state/clients.json"; }

# Draw the cards with the current index highlighted. The new rofi maps before
# the old one is closed, so moving the selection does not flash.
show() {
	local old n
	old="$(pgrep -x rofi || true)"
	n="$(count)"
	(
		exec 9>&-
		# Own pidfile per instance: rofi refuses to start next to a running one otherwise.
		picked="$(rofi -dmenu -i -markup-rows -eh 3 -format i -pid "$state/rofi-$BASHPID.pid" \
			-selected-row "$(<"$state/index")" \
			-theme "$HOME/.config/rofi/switcher.rasi" \
			-theme-str "listview { columns: $((n < 6 ? n : 6)); lines: $(((n + 5) / 6)); }" \
			<"$state/rows")" || exit 0
		# Enter or a click inside rofi picks a card directly.
		printf '%s' "$picked" >"$state/index"
		"$0" commit
	) &
	if [[ -n "$old" ]]; then
		sleep 0.08
		kill $old 2>/dev/null || true
	fi
}

finish() {
	pkill -x rofi || true
	rm -f "$state/index" "$state"/rofi-*.pid
	hyprctl dispatch 'hl.dsp.submap("reset")' >/dev/null 2>&1 || true
}

case "${1:-start}" in
	start)
		snapshot
		n="$(count)"
		if ((n == 0)); then
			finish
			exit 0
		fi
		echo "$((n > 1 ? 1 : 0))" >"$state/index" # start on the previous window
		show
		;;
	next | prev)
		[[ -e "$state/index" ]] || exit 0
		n="$(count)"
		step=$([[ "$1" == next ]] && echo 1 || echo -1)
		echo "$((($(<"$state/index") + step + n) % n))" >"$state/index"
		show
		;;
	commit)
		[[ -e "$state/index" ]] || exit 0
		address="$(jq -r --argjson i "$(<"$state/index")" '.[$i].address' "$state/clients.json")"
		finish
		hyprctl dispatch "hl.dsp.focus({ window = \"address:$address\" })" >/dev/null
		;;
	cancel)
		finish
		;;
	*)
		echo "Usage: window-switcher.sh start|next|prev|commit|cancel" >&2
		exit 1
		;;
esac
