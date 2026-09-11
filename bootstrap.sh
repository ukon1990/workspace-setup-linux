#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Detects the OS and runs the matching bootstrap script.

Options:
  --packages   Install OS packages (Linux repos or Homebrew formulas)
  --shell      Install shell tools (nvm -> Node 25 -> npm globals -> SDKMAN -> Java -> rbenv Ruby)
  --link       Link configs into your home directory
  --apps       Install downloaded vendor apps (Linux only; skipped on macOS)
  --yes        Run selected steps non-interactively; implies --packages --shell --link --apps
  --all        Same as --yes
  --dry-run    Show what would run without changing anything
  -h, --help   Show this help

OS scripts:
  Linux:  bootstrap-linux.sh
  macOS:  bootstrap-macos.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

case "$(uname -s)" in
  Darwin)
    exec "$ROOT/bootstrap-macos.sh" "$@"
    ;;
  Linux)
    exec "$ROOT/bootstrap-linux.sh" "$@"
    ;;
  *)
    echo "Unsupported operating system: $(uname -s)"
    echo 'This repo supports Linux and macOS (Darwin).'
    exit 1
    ;;
esac
