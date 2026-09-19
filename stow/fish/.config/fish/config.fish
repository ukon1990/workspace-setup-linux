# The following lines were added by Docker Desktop to add commands to your PATH.
export PATH="$PATH:/Users/jonas/.docker/bin"
# End of Docker Desktop section.

source /usr/share/cachyos-fish-config/cachyos-config.fish

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


# Added by Antigravity CLI installer
set -gx PATH "/home/jonas/.local/bin" $PATH
