function tasks
    if test -x "$HOME/scripts/tasks.sh"
        "$HOME/scripts/tasks.sh" $argv
        return $status
    end
    echo "Missing ~/scripts/tasks.sh. Re-stow the scripts package first." >&2
    return 1
end
