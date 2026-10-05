# Shared interactive Zsh setup, sourced by the bootstrap-managed .zshrc block.
if [[ -f /usr/share/cachyos-zsh-config/cachyos-config.zsh && -z ${WORKSPACE_CACHYOS_LOADED:-} ]]; then
  typeset -g WORKSPACE_CACHYOS_LOADED=1
  source /usr/share/cachyos-zsh-config/cachyos-config.zsh
fi

# Homebrew is also initialized here for terminals that start a non-login shell.
if [[ $OSTYPE == darwin* ]]; then
  workspace_brew=${commands[brew]:-}
  if [[ -z $workspace_brew ]]; then
    for workspace_brew in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [[ -x $workspace_brew ]] && break
    done
  fi
  if [[ -x $workspace_brew ]]; then
    eval "$("$workspace_brew" shellenv zsh)"
  fi
  unset workspace_brew
fi

typeset -U path
path=("$HOME/.local/bin" $path)
export PATH

if (( ! $+functions[nvm] )); then
  for workspace_nvm in "${NVM_DIR:-$HOME/.config/nvm}" "$HOME/.nvm"; do
    if [[ -s "$workspace_nvm/nvm.sh" ]]; then
      export NVM_DIR="$workspace_nvm"
      source "$NVM_DIR/nvm.sh"
      break
    fi
  done
  unset workspace_nvm
fi

if (( $+commands[rbenv] && ! $+functions[rbenv] )); then
  eval "$(rbenv init - zsh)"
fi

# Keep SDKMAN initialization last; respect an existing initialization and override.
export SDKMAN_DIR="${SDKMAN_DIR:-$HOME/.sdkman}"
if (( ! $+functions[sdk] )) && [[ -s "$SDKMAN_DIR/bin/sdkman-init.sh" ]]; then
  source "$SDKMAN_DIR/bin/sdkman-init.sh"
fi
