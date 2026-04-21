#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x "$HOME/scripts/reload-waybar.sh" ]]; then
    echo "Missing ~/scripts/reload-waybar.sh. Re-stow the scripts package first." >&2
    exit 1
fi

"$HOME/scripts/reload-waybar.sh" "$@"
