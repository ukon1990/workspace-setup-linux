#!/usr/bin/env bash
set -euo pipefail

SOURCE="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STOW_DIR="$REPO_ROOT/stow"
DRY_RUN="${DRY_RUN:-0}"

usage() {
    cat <<'EOF'
Usage: restow [--all] [package ...]

Examples:
  restow            # restow all packages
  restow scripts    # restow only the scripts package
  restow --adopt hypr
  DRY_RUN=1 restow  # preview actions
EOF
}

normalize_matching_symlinks() {
    local package src dst src_resolved dst_resolved rel_target

    for package in "${packages[@]}"; do
        while IFS= read -r -d '' src; do
            dst="$HOME/${src#"$STOW_DIR/$package/"}"
            [[ -L "$dst" ]] || continue

            src_resolved="$(readlink -f "$src" 2>/dev/null || true)"
            dst_resolved="$(readlink -f "$dst" 2>/dev/null || true)"
            [[ -n "$src_resolved" && "$src_resolved" == "$dst_resolved" ]] || continue

            rel_target="$(realpath --relative-to="$(dirname "$dst")" "$src")"
            if [[ "$DRY_RUN" == 1 ]]; then
                echo "Would normalize matching symlink: $dst -> $rel_target"
            else
                ln -snf "$rel_target" "$dst"
            fi
        done < <(find "$STOW_DIR/$package" -mindepth 1 -print0)
    done
}

if [[ "$DRY_RUN" != 1 ]] && ! command -v stow >/dev/null 2>&1; then
    echo 'stow is not installed. Install it first.'
    exit 1
fi

restow_all=1
packages=()
stow_extra_args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --all)
            restow_all=1
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                packages+=("$1")
                shift
            done
            break
            ;;
        -*)
            stow_extra_args+=("$1")
            ;;
        *)
            restow_all=0
            packages+=("$1")
            ;;
    esac
    shift
done

if [[ $restow_all -eq 1 ]]; then
    mapfile -t packages < <(find "$STOW_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
fi

if [[ ${#packages[@]} -eq 0 ]]; then
    echo "No stow packages found in $STOW_DIR"
    exit 0
fi

missing=()
for package in "${packages[@]}"; do
    [[ -d "$STOW_DIR/$package" ]] || missing+=("$package")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Unknown stow package(s): ${missing[*]}" >&2
    exit 1
fi

echo 'Restowing packages:'
printf ' - %s\n' "${packages[@]}"

normalize_matching_symlinks

stow_args=(-d "$STOW_DIR" -R -t "$HOME")
if [[ "$DRY_RUN" == 1 ]]; then
    stow_args=(-n "${stow_args[@]}")
fi

exec stow "${stow_args[@]}" "${stow_extra_args[@]}" "${packages[@]}"
