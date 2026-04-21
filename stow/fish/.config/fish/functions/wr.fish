function wr
    if not test -x "$HOME/scripts/reload-waybar.sh"
        echo "Missing ~/scripts/reload-waybar.sh. Re-stow the scripts package first." >&2
        return 1
    end

    "$HOME/scripts/reload-waybar.sh" $argv
end
