function kube-status
    if test -x "$HOME/scripts/kube-status.sh"
        "$HOME/scripts/kube-status.sh" $argv
        return $status
    end
    echo "Missing ~/scripts/kube-status.sh. Re-stow the scripts package first." >&2
    return 1
end
