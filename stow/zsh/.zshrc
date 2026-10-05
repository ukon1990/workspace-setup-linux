# Compatibility loader for machines that previously Stowed this file.
# start workspace-setup
if [[ -r "$HOME/.config/workspace-setup/zsh-init.zsh" ]]; then
  source "$HOME/.config/workspace-setup/zsh-init.zsh"
else
  # Existing links also work immediately after pulling, before the next restow.
  source "${${(%):-%x}:A:h}/.config/workspace-setup/zsh-init.zsh"
fi
# end workspace-setup
