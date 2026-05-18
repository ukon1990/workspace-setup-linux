local theme = require("theme")

hl.config({
	general = {
		gaps_in = 5,
		gaps_out = 20,
		border_size = 2,
		col = {
			active_border = theme.active_border,
			inactive_border = theme.inactive_border,
		},
		resize_on_border = false,
		allow_tearing = false,
		layout = "dwindle",
	},

	decoration = {
		rounding = 10,
		rounding_power = 2,
		active_opacity = 1.0,
		inactive_opacity = 1.0,
		shadow = {
			enabled = true,
			range = 4,
			render_power = 3,
			color = theme.shadow,
		},
		blur = {
			enabled = true,
			size = 3,
			passes = 1,
			vibrancy = 0.1696,
		},
	},

	animations = {
		enabled = true,
	},

	dwindle = {
		preserve_split = true,
	},

	master = {
		new_status = "master",
	},

	misc = {
		font_family = "Noto Sans",
		force_default_wallpaper = -1,
		disable_hyprland_logo = false,
	},

	group = {
		insert_after_current = true,
		focus_removed_window = true,
		drag_into_group = 1,
		merge_groups_on_drag = true,
		merge_groups_on_groupbar = true,
		col = {
			border_active = theme.active_border,
			border_inactive = theme.inactive_border,
		},
		groupbar = {
			enabled = true,
			font_family = "Noto Sans",
			font_size = 11,
			font_weight_active = "bold",
			font_weight_inactive = "medium",
			gradients = false,
			height = 20,
			indicator_height = 3,
			indicator_gap = 2,
			text_padding = 14,
			text_offset = 1,
			scrolling = true,
			rounding = 8,
			rounding_power = 3.0,
			gradient_rounding = 8,
			gradient_rounding_power = 3.0,
			round_only_edges = true,
			gradient_round_only_edges = true,
			text_color = theme.groupbar_text_active,
			text_color_inactive = theme.groupbar_text_inactive,
			col = {
				active = theme.groupbar_active,
				inactive = theme.groupbar_inactive,
				locked_active = theme.groupbar_locked_active,
				locked_inactive = theme.groupbar_locked_inactive,
			},
			gaps_in = 3,
			gaps_out = 4,
			keep_upper_gap = false,
			blur = true,
		},
	},
})

hl.curve("easeOutQuint", { type = "bezier", points = { { 0.23, 1 }, { 0.32, 1 } } })
hl.curve("easeInOutCubic", { type = "bezier", points = { { 0.65, 0.05 }, { 0.36, 1 } } })
hl.curve("linear", { type = "bezier", points = { { 0, 0 }, { 1, 1 } } })
hl.curve("almostLinear", { type = "bezier", points = { { 0.5, 0.5 }, { 0.75, 1 } } })
hl.curve("quick", { type = "bezier", points = { { 0.15, 0 }, { 0.1, 1 } } })

hl.animation({ leaf = "global", enabled = true, speed = 10, bezier = "default" })
hl.animation({ leaf = "border", enabled = true, speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "windows", enabled = true, speed = 4.79, bezier = "easeOutQuint" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 4.1, bezier = "easeOutQuint", style = "popin 87%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 1.49, bezier = "linear", style = "popin 87%" })
hl.animation({ leaf = "fadeIn", enabled = true, speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade", enabled = true, speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers", enabled = true, speed = 3.81, bezier = "easeOutQuint" })
hl.animation({ leaf = "layersIn", enabled = true, speed = 4, bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "layersOut", enabled = true, speed = 1.5, bezier = "linear", style = "fade" })
hl.animation({ leaf = "fadeLayersIn", enabled = true, speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut", enabled = true, speed = 1.39, bezier = "almostLinear" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 1.94, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "workspacesIn", enabled = true, speed = 1.21, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "workspacesOut", enabled = true, speed = 1.94, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "zoomFactor", enabled = true, speed = 7, bezier = "quick" })
