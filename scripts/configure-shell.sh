#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"
zsh_dir="${ZDOTDIR:-$HOME}"
start='# start workspace-setup'
end='# end workspace-setup'
profile_only=0
case "${1:-}" in
  --profile-only) profile_only=1 ;;
  '') ;;
  *) echo 'Usage: configure-shell.sh [--profile-only]' >&2; exit 1 ;;
esac

# Follow profile symlinks instead of replacing them or editing tracked configs.
resolve_file() {
  local file="$1" target directory
  while [[ -L "$file" ]]; do
    directory="$(cd "$(dirname "$file")" && pwd -P)"
    target="$(readlink "$file")"
    case "$target" in
      /*) file="$target" ;;
      *) file="$directory/$target" ;;
    esac
  done
  directory="$(cd "$(dirname "$file")" && pwd -P)"
  printf '%s/%s\n' "$directory" "$(basename "$file")"
}

write_block() {
  local file="$1" body="$2" destination temporary
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "Would update managed block in $file:"
    printf '%s\n%s\n%s\n' "$start" "$body" "$end"
    return 0
  fi
  mkdir -p "$(dirname "$file")"
  destination="$(resolve_file "$file")"
  case "$destination" in
    "$ROOT"/*)
      if [[ "$destination" == "$ROOT/stow/zsh/.zshrc" ]]; then
        echo "Keeping repository Zsh compatibility loader: $file"
        return 0
      fi
      echo "Refusing to write a user profile inside the repository: $destination" >&2
      return 1 ;;
  esac
  # Reject damaged markers rather than deleting personal settings after them.
  if [[ -f "$destination" ]]; then
    awk -v start="$start" -v end="$end" '
      $0 == start { if (inside || seen++) exit 1; inside=1 }
      $0 == end { if (!inside) exit 1; inside=0 }
      END { if (inside) exit 1 }
    ' "$destination" || { echo "Malformed managed block: $file" >&2; return 1; }
  fi
  temporary="$(mktemp "${destination}.tmp.XXXXXX")"
  local input=/dev/null
  [[ ! -f "$destination" ]] || input="$destination"
  WORKSPACE_BLOCK="$body" awk -v start="$start" -v end="$end" '
    function block() { print start; print ENVIRON["WORKSPACE_BLOCK"]; print end }
    $0 == start { block(); inside=1; seen=1; next }
    $0 == end { inside=0; next }
    !inside { print }
    END { if (!seen) block() }
  ' "$input" > "$temporary"
  if [[ -f "$destination" ]] && cmp -s "$destination" "$temporary"; then
    rm "$temporary"
    return 0
  fi
  if [[ -f "$destination" ]]; then
    [[ -e "$destination.workspace-setup.bak" ]] || cp -p "$destination" "$destination.workspace-setup.bak"
    # Preserve permissions and symlinks; only the resolved user's file is written.
    cat "$temporary" > "$destination"
    rm "$temporary"
  else
    mv "$temporary" "$destination"
  fi
  echo "Updated shell setup: $file"
}

if [[ "$(uname -s)" == Darwin ]]; then
  brew_bin="$(command -v brew || true)"
  if [[ -z "$brew_bin" ]]; then
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [[ -x "$candidate" ]]; then brew_bin="$candidate"; break; fi
    done
  fi
  if [[ -n "$brew_bin" ]]; then
    printf -v brew_quoted '%q' "$brew_bin"
    write_block "$zsh_dir/.zprofile" "eval \"\$($brew_quoted shellenv zsh)\""
  elif [[ "$DRY_RUN" == 1 ]]; then
    echo "Would persist Homebrew shellenv in $zsh_dir/.zprofile once Homebrew is installed."
  else
    echo 'Homebrew unavailable; no Homebrew profile entry added.'
  fi
fi

if [[ $profile_only -eq 0 ]]; then
  init="$HOME/.config/workspace-setup/zsh-init.zsh"
  if [[ "$DRY_RUN" != 1 && ! -f "$init" ]]; then
    echo "Missing managed Zsh initialization: $init. Resolve the zsh Stow conflict and rerun --link." >&2
    exit 2
  fi
  write_block "$zsh_dir/.zshrc" '[[ -r "$HOME/.config/workspace-setup/zsh-init.zsh" ]] && source "$HOME/.config/workspace-setup/zsh-init.zsh"'
fi
