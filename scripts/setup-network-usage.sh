#!/usr/bin/env bash
set -euo pipefail

# Keep the repository setup command as a shortcut to the network widget's installer.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/../stow/waybar/.config/waybar/scripts/widgets/network/setup.sh" "$@"
