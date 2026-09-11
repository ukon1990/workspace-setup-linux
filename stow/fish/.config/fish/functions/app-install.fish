function app-install
    if test -x "$HOME/scripts/app-install"
        "$HOME/scripts/app-install" $argv
        return $status
    end
    echo "Missing ~/scripts/app-install. Re-stow the scripts package first." >&2
    return 1
end
