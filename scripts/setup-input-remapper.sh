#!/usr/bin/env bash
set -euo pipefail

DEVICE_HINT="${1:-1532:022B}"
PRESET_NAME="${2:-tartarus}"
CONFIG_DIR="${HOME}/.config/input-remapper-2"
CONFIG_FILE="${CONFIG_DIR}/config.json"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1"
    exit 1
  }
}

extract_device_name() {
  local line="$1"
  if [[ "$line" =~ \"([^\"]+)\" ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  printf '%s\n' "$line"
}

pick_device_interactive() {
  local -n lines_ref="$1"
  local i choice

  echo
  echo "Available input-remapper devices:"
  for i in "${!lines_ref[@]}"; do
    printf '  [%d] %s\n' "$((i + 1))" "${lines_ref[$i]}"
  done
  echo
  read -r -p "Pick device number for Tartarus: " choice
  if [[ ! "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#lines_ref[@]} )); then
    echo "Invalid selection."
    exit 1
  fi
  printf '%s\n' "${lines_ref[$((choice - 1))]}"
}

need_cmd systemctl
need_cmd input-remapper-control
need_cmd python3

echo "==> Enabling input-remapper service"
sudo systemctl enable --now input-remapper

echo "==> Reading devices from input-remapper"
mapfile -t all_devices < <(sudo input-remapper-control --list-devices || true)

if [[ ${#all_devices[@]} -eq 0 ]]; then
  echo "No devices returned by input-remapper-control."
  echo "Try reconnecting device, then run:"
  echo "  sudo input-remapper-control --list-devices"
  exit 1
fi

echo "==> Trying to match hint: $DEVICE_HINT"
mapfile -t matches < <(printf '%s\n' "${all_devices[@]}" | rg -i "$DEVICE_HINT" || true)

if [[ ${#matches[@]} -eq 0 ]]; then
  # Common Tartarus naming variants if vendor:product id is not shown.
  mapfile -t matches < <(printf '%s\n' "${all_devices[@]}" | rg -i 'tartarus|razer.*keypad|razer.*tartarus' || true)
fi

if [[ ${#matches[@]} -gt 0 ]]; then
  echo "Matched devices:"
  for line in "${matches[@]}"; do
    echo "  $line"
  done
  picked_line="${matches[0]}"
else
  picked_line="$(pick_device_interactive all_devices)"
fi

device_name="$(extract_device_name "$picked_line")"

echo
echo "Using device:"
echo "  $device_name"
echo
echo "All detected devices:"
for line in "${all_devices[@]}"; do
  echo "  $line"
done
echo
read -r -p "Device name to use for autoload [$device_name]: " user_device_name
if [[ -n "${user_device_name:-}" ]]; then
  device_name="$user_device_name"
fi

mkdir -p "$CONFIG_DIR"

if [[ ! -f "$CONFIG_FILE" ]]; then
  cat > "$CONFIG_FILE" <<EOF
{
  "version": "2.2.0",
  "autoload": {}
}
EOF
fi

python3 - "$CONFIG_FILE" "$device_name" "$PRESET_NAME" <<'PY'
import json
import pathlib
import sys

config_path = pathlib.Path(sys.argv[1])
device_name = sys.argv[2]
preset = sys.argv[3]

data = {}
try:
    data = json.loads(config_path.read_text())
except Exception:
    data = {}

autoload = data.get("autoload")
if not isinstance(autoload, dict):
    autoload = {}

autoload[device_name] = preset
data["autoload"] = autoload
data.setdefault("version", "2.2.0")

config_path.write_text(json.dumps(data, indent=2) + "\n")
PY

echo "==> Autoload set"
echo "Device: $device_name"
echo "Preset: $PRESET_NAME"
echo "Config: $CONFIG_FILE"
echo
echo "Now create/import the preset in input-remapper-gtk:"
echo "  preset name must be: $PRESET_NAME"
echo
echo "Then apply immediately:"
echo "  input-remapper-control --command autoload"
