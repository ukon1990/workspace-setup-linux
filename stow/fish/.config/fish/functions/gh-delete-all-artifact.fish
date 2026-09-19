function gh-delete-all-artifact
    if not test -x "$HOME/scripts/gh-delete-all-artifact.sh"
        echo "Missing ~/scripts/gh-delete-all-artifact.sh. Re-stow the scripts package first." >&2
        return 1
    end

    "$HOME/scripts/gh-delete-all-artifact.sh" $argv
end
