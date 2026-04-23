status --is-interactive; and rbenv init - fish | source

if command -sq rbenv
    set -l ruby_version (rbenv global 2>/dev/null)
    if test -n "$ruby_version"
        set -l ruby_bin "$HOME/.rbenv/versions/$ruby_version/bin"
        test -d "$ruby_bin"; and fish_add_path "$ruby_bin"
    end
end

if command -sq ruby
    set -l user_gem_bin "$HOME/.local/share/gem/ruby/"(ruby -e 'print RbConfig::CONFIG["ruby_version"]')"/bin"
    test -d "$user_gem_bin"; and fish_add_path "$user_gem_bin"
end
