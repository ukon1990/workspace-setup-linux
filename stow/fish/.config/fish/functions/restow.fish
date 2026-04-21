function restow
    if test -x "$HOME/scripts/restow.sh"
        "$HOME/scripts/restow.sh" $argv
        return $status
    end

    echo "Missing ~/scripts/restow.sh. Re-stow the scripts package first." >&2
    return 1
end
