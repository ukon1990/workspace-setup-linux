function restow
    if test -x "$HOME/scripts/restow.sh"
        "$HOME/scripts/restow.sh" $argv
        return $status
    end

    if test -x "$HOME/dotfiles/stow/scripts/scripts/restow.sh"
        "$HOME/dotfiles/stow/scripts/scripts/restow.sh" $argv
        return $status
    end

    if test -f "$HOME/dotfiles/scripts/link-configs.sh"
        bash "$HOME/dotfiles/scripts/link-configs.sh" $argv
        return $status
    end

    echo "Missing restow helper. Make sure your dotfiles repo and scripts package exist." >&2
    return 1
end
