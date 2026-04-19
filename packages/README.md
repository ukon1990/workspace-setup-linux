# Package manifests

These files are meant to help reinstall the same apps on a fresh machine.

- `common.txt` — tiny bootstrap set
- `hyprland.txt` — packages needed for the Hyprland desktop
- `apps.txt` — daily desktop apps I installed manually
- `aur.txt` — AUR apps installed via `yay` if available
- `flatpak.txt` — optional Flatpak app IDs
- `npm-global.txt` — npm packages installed after Node is set up with nvm
- `local-installs.md` — notes for non-pacman installs

The list is intentionally curated from my real setup rather than being a full snapshot of everything preinstalled on the distro.

Secret-bearing files are not stored here; for example, `gh/hosts.yml` stays local and ignored.
Browser/app caches and profiles are also intentionally left out.
