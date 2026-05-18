local home = os.getenv("HOME")
local hypr = home .. "/.config/hypr"
local theme_bin = home .. "/.config/themes/bin/theme"
local auto_layout = hypr .. "/scripts/auto-layout/auto-monitor-layout.sh"

local function start_session()
	hl.exec_cmd("kitty")
	hl.exec_cmd("nm-applet")
	hl.exec_cmd("gnome-keyring-daemon --start --components=pkcs11,secrets,ssh")
	hl.exec_cmd(theme_bin .. " apply --quiet")
	hl.exec_cmd("waybar")
	hl.exec_cmd("hyprpaper")
	hl.exec_cmd("hyprsunset")
	hl.exec_cmd("vivaldi --profile-directory=Default")
	hl.exec_cmd("hypridle")
	hl.exec_cmd("systemctl --user start lxqt-policykit-agent.service")
	hl.exec_cmd(auto_layout .. " --daemon")
	hl.exec_cmd(auto_layout .. " --once")
end

hl.on("hyprland.start", start_session)

hl.on("config.reloaded", function()
	hl.exec_cmd(auto_layout .. " --once")
end)
