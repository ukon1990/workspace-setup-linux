-- Fallback monitor layout; auto-monitor-layout.sh adjusts when DP-1 changes width.

-- highres: Samsung ultrawide "preferred" is often a reduced PIP width (3840x1080)
hl.monitor({ output = "DP-1", mode = "highres", position = "0x0", scale = 1 })
hl.monitor({ output = "HDMI-A-1", mode = "preferred", position = "0x1440", scale = 1 })
