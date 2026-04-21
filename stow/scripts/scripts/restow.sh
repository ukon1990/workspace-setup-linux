#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
    TARGET="$(readlink "$SOURCE")"
    if [[ "$TARGET" = /* ]]; then
        SOURCE="$TARGET"
    else
        SOURCE="$(cd "$(dirname "$SOURCE")" && pwd)/$TARGET"
    fi
done

SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

exec "$REPO_ROOT/scripts/link-configs.sh" "$@"
