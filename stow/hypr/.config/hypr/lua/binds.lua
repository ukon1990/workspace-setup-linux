local mainMod = "SUPER"
local home = os.getenv("HOME")
local hypr = home .. "/.config/hypr"
local bind = require("lua.hotkeys").bind

local terminal = "kitty"
local fileManager = "dolphin"
local menu = hypr .. "/scripts/app-launcher.sh"

local hotkey_menu = hypr .. "/scripts/hotkey-menu.sh"
local lock_session = hypr .. "/scripts/lock-session.sh"
local switch_user = hypr .. "/scripts/switch-user.sh"
local screenshot_menu = hypr .. "/scripts/screenshot-menu.sh"
local window_size_menu = home .. "/.config/waybar/scripts/window_size.py overlay"

bind(mainMod .. " + T", "Open terminal", hl.dsp.exec_cmd(terminal))
bind(mainMod .. " + Q", "Close active window", hl.dsp.window.kill())
bind(
	mainMod .. " + M",
	"Exit Hyprland",
	hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'")
)
bind(mainMod .. " + E", "Open file manager", hl.dsp.exec_cmd(fileManager))
bind(mainMod .. " + V", "Toggle floating window", hl.dsp.window.float({ action = "toggle" }))
bind(mainMod .. " + SHIFT + R", "Open window size menu", hl.dsp.exec_cmd(window_size_menu))
bind(mainMod .. " + SPACE", "Open application launcher", hl.dsp.exec_cmd(menu))
bind(mainMod .. " + H", "Show searchable hotkeys", hl.dsp.exec_cmd(hotkey_menu))
bind(mainMod .. " + L", "Lock session", hl.dsp.exec_cmd(lock_session))
bind(mainMod .. " + SHIFT + L", "Switch user", hl.dsp.exec_cmd(switch_user))
bind(mainMod .. " + P", "Toggle pseudotiling", hl.dsp.window.pseudo())
bind(mainMod .. " + J", "Toggle split direction", hl.dsp.layout("togglesplit"))

bind("Print", "Open screenshot menu", hl.dsp.exec_cmd(screenshot_menu))

bind(mainMod .. " + G", "Toggle window group", hl.dsp.group.toggle())
bind(mainMod .. " + TAB", "Focus next window in group", hl.dsp.group.next())
bind(mainMod .. " + SHIFT + TAB", "Focus previous window in group", hl.dsp.group.prev())
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
