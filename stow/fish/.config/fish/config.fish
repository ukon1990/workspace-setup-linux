# The following lines were added by Docker Desktop to add commands to your PATH.
if test -d "$HOME/.docker/bin"
    set -gx PATH $PATH "$HOME/.docker/bin"
end
# End of Docker Desktop section.

if test -f /usr/share/cachyos-fish-config/cachyos-config.fish
    source /usr/share/cachyos-fish-config/cachyos-config.fish
end

set -l podman_socket /run/user/(id -u)/podman/podman.sock
if test -S $podman_socket
    set -gx DOCKER_HOST unix://$podman_socket
    set -gx TESTCONTAINERS_RYUK_DISABLED true
end

# overwrite greeting
# potentially disabling fastfetch
#function fish_greeting
#    # smth smth
#end


# User local binaries (restow and other helpers)
fish_add_path "$HOME/.local/bin"
