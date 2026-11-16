-- The main monitor is an ultrawide used at two widths. At full width (5120 px)
-- tiles go centre-first with side columns and the bar moves over the centre
-- column; at half width the regular dwindle layout stays.
local MAIN_MONITOR = "DP-1"
local WIDE = 5120
local waybar = os.getenv("HOME") .. "/.config/waybar/scripts/launch.sh --if-changed"

hl.config({
	master = {
		orientation = "center",
		mfact = 0.5,
		new_status = "slave",
	},
})

local function apply()
	local monitor = hl.get_monitor(MAIN_MONITOR)
	if monitor == nil then
		return
	end
	hl.config({ general = { layout = monitor.width >= WIDE and "master" or "dwindle" } })
	hl.exec_cmd(waybar)
end

hl.on("hyprland.start", apply)
hl.on("config.reloaded", apply)
hl.on("monitor.layout_changed", apply)
