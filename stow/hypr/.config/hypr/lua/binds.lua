local mainMod = "SUPER"
local home = os.getenv("HOME")
local hypr = home .. "/.config/hypr"

local terminal = "kitty"
local fileManager = "dolphin"
local menu = "sherlock"

local lock_session = hypr .. "/scripts/lock-session.sh"
local switch_user = hypr .. "/scripts/switch-user.sh"

hl.bind(mainMod .. " + T", hl.dsp.exec_cmd(terminal))
hl.bind(mainMod .. " + Q", hl.dsp.window.kill())
hl.bind(
	mainMod .. " + M",
	hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'")
)
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + SPACE", hl.dsp.exec_cmd(menu))
hl.bind(mainMod .. " + L", hl.dsp.exec_cmd(lock_session))
hl.bind(mainMod .. " + SHIFT + L", hl.dsp.exec_cmd(switch_user))
hl.bind(mainMod .. " + P", hl.dsp.window.pseudo())
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"))

hl.bind(mainMod .. " + G", hl.dsp.group.toggle())
hl.bind(mainMod .. " + TAB", hl.dsp.group.next())
hl.bind(mainMod .. " + SHIFT + TAB", hl.dsp.group.prev())
hl.bind(mainMod .. " + SHIFT + G", hl.dsp.window.move({ out_of_group = true }))
hl.bind(mainMod .. " + SHIFT + left", hl.dsp.window.move({ direction = "l", group_aware = true }))
hl.bind(mainMod .. " + SHIFT + right", hl.dsp.window.move({ direction = "r", group_aware = true }))
hl.bind(mainMod .. " + SHIFT + up", hl.dsp.window.move({ direction = "u", group_aware = true }))
hl.bind(mainMod .. " + SHIFT + down", hl.dsp.window.move({ direction = "d", group_aware = true }))

hl.bind(mainMod .. " + left", hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + up", hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down", hl.dsp.focus({ direction = "down" }))

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
	hl.bind(mainMod .. " + " .. s, function()
		local ws, mon = workspace_for_slot(s)
		maybe_move_workspace(ws, mon)
		hl.dispatch(hl.dsp.focus({ workspace = ws }))
	end)
	hl.bind(mainMod .. " + SHIFT + " .. s, function()
		local ws = workspace_for_slot(s)
		hl.dispatch(hl.dsp.window.move({ workspace = ws }))
	end)
end

for ws = 6, 10 do
	local key = ws % 10
	hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ workspace = ws }))
	hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = ws }))
end

hl.bind(mainMod .. " + S", hl.dsp.workspace.toggle_special("magic"))
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))

hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse_up", hl.dsp.focus({ workspace = "e-1" }))

hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mainMod .. " + SHIFT + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

hl.bind(
	"XF86AudioRaiseVolume",
	hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"),
	{ locked = true, repeating = true }
)
hl.bind(
	"XF86AudioLowerVolume",
	hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),
	{ locked = true, repeating = true }
)
hl.bind(
	"XF86AudioMute",
	hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),
	{ locked = true }
)
hl.bind(
	"XF86AudioMicMute",
	hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),
	{ locked = true }
)
hl.bind(
	"XF86MonBrightnessUp",
	hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),
	{ locked = true, repeating = true }
)
hl.bind(
	"XF86MonBrightnessDown",
	hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),
	{ locked = true, repeating = true }
)

hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), { locked = true })
