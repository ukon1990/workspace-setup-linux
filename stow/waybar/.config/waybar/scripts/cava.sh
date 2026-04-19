#!/usr/bin/env bash
# Stream cava bars into Waybar as unicode block chars.
# Each frame from cava is a sequence of digits 0..7 which this script maps
# to ▁▂▃▄▅▆▇█ so the widget renders as a tiny audio spectrum.

set -u

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/waybar/cava/config"

if ! command -v cava >/dev/null 2>&1; then
    # cava missing: emit one empty line so Waybar hides the widget
    # (requires `hide-empty-text: true` on the module) and exit.
    echo ""
    exit 0
fi

if [[ ! -f "$CONFIG" ]]; then
    echo ""
    exit 0
fi

# Translate cava's "<d>;<d>;...;<d>" frames into unicode blocks.
# Note: sed -u keeps the stream unbuffered so Waybar redraws every frame.
# The order matters only in that we strip the delimiter first; the digit
# substitutions don't chain because their replacements are non-digit glyphs.
exec cava -p "$CONFIG" | sed -u \
    -e 's/;//g' \
    -e 's/0/▁/g' \
    -e 's/1/▂/g' \
    -e 's/2/▃/g' \
    -e 's/3/▄/g' \
    -e 's/4/▅/g' \
    -e 's/5/▆/g' \
    -e 's/6/▇/g' \
    -e 's/7/█/g'
