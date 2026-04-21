#!/usr/bin/env bash

set -euo pipefail

ENV_VAR_NAME="CLOSEPORTS_DEFAULT_PORTS"

usage() {
  echo "Usage: closeports <port> [<port> ...]" >&2
  echo "Closes any processes listening on the given TCP/UDP ports." >&2
  echo "If no ports are provided, ports are read from \$$ENV_VAR_NAME." >&2
  echo "Example: export $ENV_VAR_NAME=\"1433 4200 5201\"" >&2
}

if ! command -v lsof >/dev/null 2>&1; then
  echo "Error: 'lsof' is required but not found. Install it and retry." >&2
  exit 1
fi

ports_to_close=("$@")

if [ ${#ports_to_close[@]} -eq 0 ] && [ -n "${!ENV_VAR_NAME:-}" ]; then
  # shellcheck disable=SC2206
  ports_to_close=(${!ENV_VAR_NAME})
  echo "No ports provided; using \$$ENV_VAR_NAME: ${ports_to_close[*]}" >&2
fi

if [ ${#ports_to_close[@]} -eq 0 ]; then
  echo "No ports provided, and \$$ENV_VAR_NAME is not set." >&2
  usage
  exit 1
fi

is_number() {
  case $1 in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

any_failed=0
declare -A seen_pid

for port in "${ports_to_close[@]}"; do
  if ! is_number "$port" || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "Skipping invalid port: $port" >&2
    any_failed=1
    continue
  fi

  # Collect PIDs listening on this port (TCP LISTEN + UDP)
  mapfile -t pids_tcp < <(lsof -nP -ti TCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  mapfile -t pids_udp < <(lsof -nP -ti UDP:"$port" 2>/dev/null || true)

  pids=("${pids_tcp[@]:-}" "${pids_udp[@]:-}")

  # Deduplicate and filter empties
  uniq_pids=()
  for pid in "${pids[@]}"; do
    [ -z "${pid:-}" ] && continue
    if [ -z "${seen_pid[$pid]:-}" ]; then
      uniq_pids+=("$pid")
      seen_pid[$pid]=1
    fi
  done

  if [ ${#uniq_pids[@]} -eq 0 ]; then
    echo "No process is listening on port $port"
    continue
  fi

  echo "Closing processes on port $port: ${uniq_pids[*]}"

  # Try graceful termination first
  if ! kill "${uniq_pids[@]}" 2>/dev/null; then
    echo "kill SIGTERM failed for some PIDs; trying sudo (you may be prompted)." >&2
    if ! sudo kill "${uniq_pids[@]}" 2>/dev/null; then
      true # ignore here; we'll enforce with -9 below if needed
    fi
  fi

  # Wait briefly for processes to exit
  deadline=$((SECONDS + 3))
  remaining=()
  while [ $SECONDS -lt $deadline ]; do
    remaining=()
    for pid in "${uniq_pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        remaining+=("$pid")
      fi
    done
    [ ${#remaining[@]} -eq 0 ] && break
    sleep 0.2
  done

  if [ ${#remaining[@]} -gt 0 ]; then
    echo "Forcing kill for remaining PIDs: ${remaining[*]}" >&2
    if ! kill -9 "${remaining[@]}" 2>/dev/null; then
      echo "kill -9 failed for some PIDs; trying sudo -9 (you may be prompted)." >&2
      sudo kill -9 "${remaining[@]}" 2>/dev/null || true
    fi
  fi

done

exit $any_failed

