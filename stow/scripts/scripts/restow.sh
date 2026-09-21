#!/usr/bin/env bash
set -euo pipefail

resolve_path() {
    local source="$1" directory
    while [[ -L "$source" ]]; do
        directory="$(cd -P "$(dirname "$source")" && pwd)"
        source="$(readlink "$source")"
        [[ "$source" == /* ]] || source="$directory/$source"
    done
    if [[ -d "$source" ]]; then
        (cd -P "$source" && pwd)
    else
        directory="$(cd -P "$(dirname "$source")" && pwd)"
        printf '%s/%s\n' "$directory" "$(basename "$source")"
    fi
}

relative_path() {
    python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
}

SOURCE="$(resolve_path "${BASH_SOURCE[0]}")"
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

            src_resolved="$(resolve_path "$src" 2>/dev/null || true)"
            dst_resolved="$(resolve_path "$dst" 2>/dev/null || true)"
            [[ -n "$src_resolved" && "$src_resolved" == "$dst_resolved" ]] || continue

            rel_target="$(relative_path "$src" "$(dirname "$dst")")"
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
    packages=()
    while IFS= read -r package; do
        [[ -n "$package" ]] || continue
        packages+=("$(basename "$package")")
    done < <(find "$STOW_DIR" -mindepth 1 -maxdepth 1 -type d | sort)
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
echo

normalize_matching_symlinks

ok=()
skipped_conflicts=()
failed=()

restow_pkg() {
    local pkg="$1"
    local args=(-d "$STOW_DIR" -R -t "$HOME")
    local output="" status=0

    [[ "$DRY_RUN" == 1 ]] && args+=(-n)
    args+=("${stow_extra_args[@]}" "$pkg")

    echo "==> restow $pkg"
    set +e
    output="$(stow "${args[@]}" 2>&1)"
    status=$?
    set -e

    [[ -n "$output" ]] && printf '%s\n' "$output"

    if [[ $status -eq 0 ]]; then
        ok+=("$pkg")
        return 0
    fi

    if printf '%s\n' "$output" | grep -qi 'would cause conflicts\|existing target'; then
        echo "Skipping $pkg due to existing files (not adopting)."
        skipped_conflicts+=("$pkg")
        return 0
    fi

    echo "Failed to restow $pkg (exit $status)"
    failed+=("$pkg")
}

for package in "${packages[@]}"; do
    restow_pkg "$package"
    echo
done

echo '==> Restow report'
if [[ ${#ok[@]} -gt 0 ]]; then
    echo 'Ok:'
    printf '  - %s\n' "${ok[@]}"
else
    echo 'Ok: (none)'
fi
if [[ ${#skipped_conflicts[@]} -gt 0 ]]; then
    echo 'Skipped (conflicts with existing files):'
    printf '  - %s\n' "${skipped_conflicts[@]}"
    echo "Resolve with: restow --adopt ${skipped_conflicts[*]}"
fi
if [[ ${#failed[@]} -gt 0 ]]; then
    echo 'Failed:'
    printf '  - %s\n' "${failed[@]}"
    exit 1
fi
echo 'Failed: (none)'
