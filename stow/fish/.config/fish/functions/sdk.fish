function sdk --description "SDKMAN wrapper for fish shell"
    set -l sdkman_dir "$HOME/.sdkman"

    if not test -s "$sdkman_dir/bin/sdkman-init.sh"
        echo "SDKMAN is not installed at $sdkman_dir" >&2
        return 1
    end

    set -l escaped_args (string join " " -- (string escape -- $argv))
    bash -lc "source \"$sdkman_dir/bin/sdkman-init.sh\" && sdk $escaped_args"
end
