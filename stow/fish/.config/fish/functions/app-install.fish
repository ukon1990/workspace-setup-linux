function app-install
    if test -x "$HOME/scripts/app-install.sh"
        "$HOME/scripts/app-install.sh" $argv
        return $status
    end
    echo "Missing ~/scripts/app-install.sh. Re-stow the scripts package first." >&2
    return 1
end
