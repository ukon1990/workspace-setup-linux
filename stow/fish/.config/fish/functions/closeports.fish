function closeports
    if not test -x "$HOME/scripts/closeports.sh"
        echo "Missing ~/scripts/closeports.sh. Re-stow the scripts package first." >&2
        return 1
    end

    "$HOME/scripts/closeports.sh" $argv
end
