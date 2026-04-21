function collect-pr
    if not test -f "$HOME/scripts/collect-pr.py"
        echo "Missing ~/scripts/collect-pr.py. Re-stow the scripts package first." >&2
        return 1
    end

    python3 "$HOME/scripts/collect-pr.py" $argv
end
