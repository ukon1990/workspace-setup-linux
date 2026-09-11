# Package manifests

These files are meant to help reinstall the same apps on a fresh machine.

## Linux (pacman / AUR / Flatpak)
- `common.txt` — tiny bootstrap set (includes `neovim` + `tree-sitter` lib/CLI for nvim-treesitter builds)
- `hyprland.txt` — packages needed for the Hyprland desktop
- `apps.txt` — daily desktop apps I installed manually
- `aur.txt` — AUR apps installed via `yay` if available
- `flatpak.txt` — optional Flatpak app IDs

## macOS (Homebrew)
- `brew.txt` — Homebrew formulas installed by `scripts/install-brew-packages.sh` (includes `tree-sitter` + `tree-sitter-cli`; brew split them the same way Arch did)
- `brew-casks.txt` — Homebrew casks (e.g. `ollama-app`) installed by the same script
- Installs are per-package: already-installed items are skipped, optional failures are reported, and only essential formulas (`git`, `stow`, `curl`) hard-fail

## Shared
- `npm-global.txt` — npm packages installed after Node is set up with nvm
- `stow-shared.txt` — stow packages linked on both Linux and macOS
- `stow-linux.txt` — stow packages linked on Linux only
- `local-installs.md` — notes for non-pacman installs

The list is intentionally curated from my real setup rather than being a full snapshot of everything preinstalled on the distro.

Secret-bearing files are not stored here; for example, `gh/hosts.yml` stays local and ignored.
Browser/app caches and profiles are also intentionally left out.
