local mainMod = "SUPER"
local home = os.getenv("HOME")
local hypr = home .. "/.config/hypr"
local bind = require("lua.hotkeys").bind

local terminal = "kitty"
local fileManager = "dolphin"
local menu = hypr .. "/scripts/app-launcher.sh"
local window_switcher = hypr .. "/scripts/window-switcher.sh"
local clipboard_menu = hypr .. "/scripts/clipboard-menu.sh"
local gamemode = require("lua.gamemode")

local hotkey_menu = hypr .. "/scripts/hotkey-menu.sh"
local lock_session = hypr .. "/scripts/lock-session.sh"
local switch_user = hypr .. "/scripts/switch-user.sh"
local screenshot_menu = hypr .. "/scripts/screenshot-menu.sh"
local window_size_menu = home .. "/.config/waybar/scripts/window_size.py overlay"
local wallpaper_picker = home .. "/.config/themes/bin/theme wallpaper picker"

bind(mainMod .. " + T", "Open terminal", hl.dsp.exec_cmd(terminal))
bind(mainMod .. " + Q", "Close active window", hl.dsp.window.kill())
bind(
	mainMod .. " + SHIFT + Escape",
	"Exit Hyprland",
	hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'")
)
bind(mainMod .. " + E", "Open file manager", hl.dsp.exec_cmd(fileManager))
bind(mainMod .. " + V", "Toggle floating window", hl.dsp.window.float({ action = "toggle" }))
bind(mainMod .. " + F", "Toggle fullscreen", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
bind(mainMod .. " + SHIFT + F", "Toggle maximize (keeps the bar)", hl.dsp.window.fullscreen({ mode = "maximized" }))
-- Window switcher: hold Super, tap Tab to move, release Super to switch.
-- Hyprland handles the keys so the release is seen; rofi only draws the cards.
-- A release *bind* on Super is skipped after a key combo, so the release is
-- read from the raw key event instead. Super_L/R are XKB keycodes 133/134
-- (evdev 125/126, accepted too in case the event reports those).
local SUPER_KEYCODES = { [133] = true, [134] = true, [125] = true, [126] = true }
local KEY_RELEASED = 0
local function switcher(action)
	return hl.dsp.exec_cmd(window_switcher .. " " .. action)
end
bind(mainMod .. " + TAB", "Switch window (hold Super, tap Tab, release)", function()
	hl.dispatch(hl.dsp.submap("switcher"))
	hl.dispatch(switcher("start"))
end)
hl.define_submap("switcher", function()
	hl.bind(mainMod .. " + TAB", switcher("next"))
	hl.bind(mainMod .. " + SHIFT + TAB", switcher("prev"))
	hl.bind(mainMod .. " + Escape", switcher("cancel"))
	hl.bind("Escape", switcher("cancel"))
end)
hl.on("input.keyboard.key", function(keycode, _time, key_state)
	if key_state == KEY_RELEASED and SUPER_KEYCODES[keycode] and hl.get_current_submap() == "switcher" then
		hl.dispatch(switcher("commit"))
	end
end)

bind(mainMod .. " + R", "Enter resize mode (arrows resize, Escape leaves)", hl.dsp.submap("resize"))
hl.define_submap("resize", function()
	local step = 40
	hl.bind("right", hl.dsp.window.resize({ x = step, y = 0, relative = true }), { repeating = true })
	hl.bind("left", hl.dsp.window.resize({ x = -step, y = 0, relative = true }), { repeating = true })
	hl.bind("down", hl.dsp.window.resize({ x = 0, y = step, relative = true }), { repeating = true })
	hl.bind("up", hl.dsp.window.resize({ x = 0, y = -step, relative = true }), { repeating = true })
	hl.bind("escape", hl.dsp.submap("reset"))
	hl.bind("Return", hl.dsp.submap("reset"))
end)

bind(mainMod .. " + SHIFT + T", "Toggle dropdown terminal", hl.dsp.workspace.toggle_special("term"))
bind(mainMod .. " + C", "Open clipboard history", hl.dsp.exec_cmd(clipboard_menu))
bind(mainMod .. " + SHIFT + C", "Pick a colour to the clipboard", hl.dsp.exec_cmd("hyprpicker -a"))
bind(mainMod .. " + N", "Toggle do not disturb", hl.dsp.exec_cmd("makoctl mode -t do-not-disturb"))
bind(mainMod .. " + F9", "Toggle game mode", gamemode.toggle)
bind(mainMod .. " + SHIFT + R", "Open window size menu", hl.dsp.exec_cmd(window_size_menu))
bind(mainMod .. " + SHIFT + W", "Choose wallpaper", hl.dsp.exec_cmd(wallpaper_picker))
bind(mainMod .. " + SPACE", "Open application launcher", hl.dsp.exec_cmd(menu))
bind(mainMod .. " + H", "Show searchable hotkeys", hl.dsp.exec_cmd(hotkey_menu))
bind(mainMod .. " + L", "Lock session", hl.dsp.exec_cmd(lock_session))
bind(mainMod .. " + SHIFT + L", "Switch user", hl.dsp.exec_cmd(switch_user))
bind(mainMod .. " + P", "Toggle pseudotiling", hl.dsp.window.pseudo())
bind(mainMod .. " + J", "Toggle split direction", hl.dsp.layout("togglesplit"))

bind("Print", "Open screenshot menu", hl.dsp.exec_cmd(screenshot_menu))

bind(mainMod .. " + G", "Toggle window group", hl.dsp.group.toggle())
bind("ALT + TAB", "Focus next tab in group", hl.dsp.group.next())
bind("ALT + SHIFT + TAB", "Focus previous tab in group", hl.dsp.group.prev())
bind(mainMod .. " + CTRL + G", "Lock group (new windows stop joining)", hl.dsp.group.lock({ action = "toggle" }))
bind(mainMod .. " + CTRL + left", "Move tab left in group", hl.dsp.group.move_window({ forward = false }))
bind(mainMod .. " + CTRL + right", "Move tab right in group", hl.dsp.group.move_window({ forward = true }))
for tab = 1, 9 do
	bind(mainMod .. " + CTRL + " .. tab, ("Jump to tab %d in group"):format(tab), hl.dsp.group.active({ index = tab }))
end
bind(mainMod .. " + SHIFT + G", "Move window out of group", hl.dsp.window.move({ out_of_group = true }))
bind(
	mainMod .. " + SHIFT + left",
	"Move window left",
	hl.dsp.window.move({ direction = "l", group_aware = true })
)
bind(
	mainMod .. " + SHIFT + right",
	"Move window right",
	hl.dsp.window.move({ direction = "r", group_aware = true })
)
bind(
	mainMod .. " + SHIFT + up",
	"Move window up",
	hl.dsp.window.move({ direction = "u", group_aware = true })
)
bind(
	mainMod .. " + SHIFT + down",
	"Move window down",
	hl.dsp.window.move({ direction = "d", group_aware = true })
)

bind(mainMod .. " + left", "Focus window left", hl.dsp.focus({ direction = "left" }))
bind(mainMod .. " + right", "Focus window right", hl.dsp.focus({ direction = "right" }))
bind(mainMod .. " + up", "Focus window above", hl.dsp.focus({ direction = "up" }))
bind(mainMod .. " + down", "Focus window below", hl.dsp.focus({ direction = "down" }))

local SLOTS_PER_MONITOR = 5
local PREFERRED_MONITORS = { "DP-1", "HDMI-A-1" }

local function ordered_monitor_names()
	local monitors = hl.get_monitors()
	local by_name = {}
	for _, m in ipairs(monitors) do
		by_name[m.name] = true
	end

	local ordered = {}
	local seen = {}
	for _, preferred in ipairs(PREFERRED_MONITORS) do
		if by_name[preferred] then
			table.insert(ordered, preferred)
			seen[preferred] = true
		end
	end

	local rest = {}
	for _, m in ipairs(monitors) do
		if not seen[m.name] then
			table.insert(rest, m.name)
		end
	end
	table.sort(rest)

	for _, name in ipairs(rest) do
		table.insert(ordered, name)
	end

	return ordered
end

local function monitor_index(name)
	for i, n in ipairs(ordered_monitor_names()) do
		if n == name then
			return i - 1
		end
	end
	error("focused monitor missing from monitor list")
end

local function workspace_for_slot(slot)
	local focused = hl.get_active_monitor()
	local ws = monitor_index(focused.name) * SLOTS_PER_MONITOR + slot
	return ws, focused.name
end

local function maybe_move_workspace(ws, monitor_name)
	local workspace = hl.get_workspace(ws)
	if workspace and workspace.monitor ~= monitor_name then
		hl.dispatch(hl.dsp.workspace.move({ workspace = ws, monitor = monitor_name }))
	end
end

for slot = 1, 5 do
	local s = slot
	bind(mainMod .. " + " .. s, ("Focus workspace slot %d on current monitor"):format(s), function()
		local ws, mon = workspace_for_slot(s)
		maybe_move_workspace(ws, mon)
		hl.dispatch(hl.dsp.focus({ workspace = ws }))
	end)
	bind(mainMod .. " + SHIFT + " .. s, ("Move window to workspace slot %d"):format(s), function()
		local ws = workspace_for_slot(s)
		hl.dispatch(hl.dsp.window.move({ workspace = ws }))
	end)
end

for ws = 6, 10 do
	local key = ws % 10
	bind(mainMod .. " + " .. key, ("Focus workspace %d"):format(ws), hl.dsp.focus({ workspace = ws }))
	bind(
		mainMod .. " + SHIFT + " .. key,
		("Move window to workspace %d"):format(ws),
		hl.dsp.window.move({ workspace = ws })
	)
end

bind(mainMod .. " + S", "Toggle scratchpad workspace", hl.dsp.workspace.toggle_special("magic"))
bind(mainMod .. " + SHIFT + S", "Move window to scratchpad", hl.dsp.window.move({ workspace = "special:magic" }))

bind(mainMod .. " + mouse_down", "Focus next workspace", hl.dsp.focus({ workspace = "e+1" }))
bind(mainMod .. " + mouse_up", "Focus previous workspace", hl.dsp.focus({ workspace = "e-1" }))

bind(mainMod .. " + mouse:272", "Drag window", hl.dsp.window.drag(), { mouse = true })
bind(mainMod .. " + SHIFT + mouse:272", "Drag window out of group", hl.dsp.window.drag(), { mouse = true })
bind(mainMod .. " + mouse:273", "Resize window", hl.dsp.window.resize(), { mouse = true })

bind(
	"XF86AudioRaiseVolume",
	"Raise volume",
	hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"),
	{ locked = true, repeating = true }
)
bind(
	"XF86AudioLowerVolume",
	"Lower volume",
	hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),
	{ locked = true, repeating = true }
)
bind(
	"XF86AudioMute",
	"Toggle output mute",
	hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),
	{ locked = true }
)
bind(
	"XF86AudioMicMute",
	"Toggle microphone mute",
	hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),
	{ locked = true }
)
bind(
	"XF86MonBrightnessUp",
	"Raise display brightness",
	hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),
	{ locked = true, repeating = true }
)
bind(
	"XF86MonBrightnessDown",
	"Lower display brightness",
	hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),
	{ locked = true, repeating = true }
)

bind("XF86AudioNext", "Play next media track", hl.dsp.exec_cmd("playerctl next"), { locked = true })
bind("XF86AudioPause", "Toggle media playback", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
bind("XF86AudioPlay", "Toggle media playback", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
bind("XF86AudioPrev", "Play previous media track", hl.dsp.exec_cmd("playerctl previous"), { locked = true })
