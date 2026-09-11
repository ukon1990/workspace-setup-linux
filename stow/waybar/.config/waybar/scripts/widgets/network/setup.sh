#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$EUID" -ne 0 ]]; then
    exec sudo bash "$SCRIPT_DIR/setup.sh" "$@"
fi

if ! command -v nethogs >/dev/null 2>&1; then
    pacman -S --needed nethogs
fi
# Copy root-owned code; never run a user-writable repository symlink as root.
install -d -o root -g root -m 0755 /usr/local/lib/waybar-network
install -o root -g root -m 0644 "$SCRIPT_DIR/collector.py" /usr/local/lib/waybar-network/collector.py
install -o root -g root -m 0644 "$SCRIPT_DIR/waybar-network.service" /etc/systemd/system/waybar-network.service
systemctl daemon-reload
systemctl enable waybar-network.service
systemctl restart waybar-network.service
systemctl --no-pager status waybar-network.service
