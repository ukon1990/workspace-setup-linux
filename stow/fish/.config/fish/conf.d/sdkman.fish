set -gx SDKMAN_DIR "$HOME/.sdkman"

function __sdkman_sync_java --description "Sync JAVA_HOME and PATH from SDKMAN current java"
    set -l sdk_java_root "$SDKMAN_DIR/candidates/java"
    set -l current_link "$sdk_java_root/current"

    if test -L "$current_link" -o -d "$current_link"
        set -l current_home (realpath "$current_link")
        set -l cleaned_path

        for entry in $PATH
            if not string match -q "$sdk_java_root/*/bin" -- $entry
                set cleaned_path $cleaned_path $entry
            end
        end

        set -gx JAVA_HOME $current_home
        set -gx PATH "$JAVA_HOME/bin" $cleaned_path
    else
        set -e JAVA_HOME
    end
end

__sdkman_sync_java
