for i = 1, 5 do
	hl.workspace_rule({ workspace = tostring(i), monitor = "DP-1" })
end

for i = 6, 10 do
	hl.workspace_rule({ workspace = tostring(i), monitor = "HDMI-A-1" })
end

hl.window_rule({
	name = "suppress-maximize-events",
	match = { class = ".*" },
	suppress_event = "maximize",
})

hl.window_rule({
	name = "fix-xwayland-drags",
	match = {
		class = "^$",
		title = "^$",
		xwayland = true,
		float = true,
		fullscreen = false,
		pin = false,
	},
	no_focus = true,
})

hl.window_rule({
	name = "move-hyprland-run",
	match = { class = "hyprland-run" },
	move = "20 monitor_h-120",
	float = true,
})

-- Wine/Proton windows share the class steam_app_*; launchers are told apart by title.
local LAUNCHER_TITLE = "^(Battle\\.net.*|Steam.*|Lutris.*)$"

-- Games: normal tile on the current workspace (bar stays visible, other windows
-- can sit beside it), never pulled into a tab group automatically. Super+F goes
-- true fullscreen, which is also when tearing (immediate) and VRR apply.
hl.window_rule({
	name = "games",
	match = { class = "^(steam_app_.*|gamescope)$", title = "negative:" .. LAUNCHER_TITLE },
	group = "barred",
	content = "game",
	immediate = true,
	idle_inhibit = "always",
	no_blur = true,
	no_shadow = true,
})

hl.window_rule({
	name = "dialogs-stay-out-of-groups",
	match = { modal = true },
	group = "barred",
})

hl.workspace_rule({ workspace = "special:term", on_created_empty = "kitty" })

hl.layer_rule({
	name = "rofi-backdrop",
	match = { namespace = "^rofi$" },
	blur = true,
	ignore_alpha = 0.5,
	-- No dim_around: the switcher respawns rofi on every Tab, and each new dim
	-- fades in from zero, blinking the whole screen bright.
	no_anim = true, -- the switcher redraws on every Tab
})
