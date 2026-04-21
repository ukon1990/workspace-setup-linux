#!/usr/bin/env bash
set -euo pipefail

MAIN_MONITOR="${MAIN_MONITOR:-DP-1}"
SECONDARY_MONITOR="${SECONDARY_MONITOR:-HDMI-A-1}"
POLL_SECONDS="${POLL_SECONDS:-2}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LAYOUT_SCRIPT="$SCRIPT_DIR/monitor_layout.py"

log_warn() {
    printf '[auto-monitor-layout] %s\n' "$*" >&2
}

build_layout() {
    hyprctl monitors -j | python3 "$LAYOUT_SCRIPT" "$MAIN_MONITOR" "$SECONDARY_MONITOR"
}

extract_state() {
    local layout_output="$1"

    while IFS=$'\t' read -r kind value; do
        if [[ "$kind" == "STATE" ]]; then
            printf '%s\n' "$value"
            return 0
        fi
    done <<< "$layout_output"
}

apply_layout() {
    local layout_output state=""

    layout_output="$(build_layout)"
    while IFS=$'\t' read -r kind value; do
        case "$kind" in
            STATE)
                state="$value"
                ;;
            CMD)
                hyprctl keyword monitor "$value" >/dev/null
                ;;
        esac
    done <<< "$layout_output"

    printf '%s\n' "$state"
}

run_once() {
    if ! apply_layout >/dev/null; then
        log_warn "run_once failed; monitor state may be transient"
    fi
}

run_daemon() {
    local lock_file="${XDG_RUNTIME_DIR:-/tmp}/hypr-auto-monitor-layout.lock"
    local last_state="" current_state="" layout_output=""

    exec 9>"$lock_file"
    flock -n 9 || exit 0

    if last_state="$(apply_layout 2>/dev/null)"; then
        :
    else
        log_warn "initial layout apply failed; daemon will keep retrying"
        last_state=""
    fi

    while true; do
        sleep "$POLL_SECONDS"

        if ! layout_output="$(build_layout 2>/dev/null)"; then
            log_warn "failed to query/build monitor layout; retrying"
            continue
        fi

        current_state="$(extract_state "$layout_output" || true)"
        if [[ -z "$current_state" ]]; then
            log_warn "layout output missing STATE; skipping this poll"
            continue
        fi

        if [[ "$current_state" != "$last_state" ]]; then
            if last_state="$(apply_layout 2>/dev/null)"; then
                :
            else
                log_warn "failed to apply layout update; keeping daemon alive"
            fi
        fi
    done
}

case "${1:---daemon}" in
    --once)
        run_once
        ;;
    --daemon)
        run_daemon
        ;;
    *)
        echo "Usage: $0 [--once|--daemon]" >&2
        exit 1
        ;;
esac
