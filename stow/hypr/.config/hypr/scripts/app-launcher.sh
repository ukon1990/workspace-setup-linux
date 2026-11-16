#!/usr/bin/env bash
# Super+Space: toggle the rofi launcher (apps, windows, run).
set -euo pipefail

pkill -x rofi && exit 0
exec rofi -show drun -theme "$HOME/.config/rofi/launcher.rasi"
