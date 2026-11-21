hl.config({
	input = {
		kb_layout = "no,us",
		kb_variant = "",
		kb_model = "",
		kb_options = "",
		kb_rules = "",

		follow_mouse = 1,
		sensitivity = 0,

		touchpad = {
			natural_scroll = false,
		},
	},
})

hl.gesture({
	fingers = 3,
	direction = "horizontal",
	action = "workspace",
})

hl.device({
	name = "epic-mouse-v1",
	sensitivity = -0.5,
})

-- Each keyboard keeps its own lock state. A Caps Lock tapped on the Tartarus
-- keypad stays latched there (the Varmilo LED never shows it) and leaks into
-- whichever window gets focus next, so the keypad's Caps key is disabled.
for _, name in ipairs({ "razer-razer-tartarus-v2", "razer-razer-tartarus-v2-1", "razer-razer-tartarus-v2-3" }) do
	hl.device({ name = name, kb_options = "caps:none" })
end

hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
