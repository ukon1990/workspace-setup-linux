# dotfiles

My workstation config repo.

This repo is meant to be **public-safe**:
- no secrets
- no SSH keys
- no tokens or private credentials
- no browser profiles or cache

## What lives here
- Hyprland config
- Waybar config
- Mako config
- theme manager + palettes
- shell config
- gh config
- sherlock config
- lxqt + policykit session config
- package lists for reinstalling apps on a fresh system
- vendor app installer for downloaded tar.gz/AppImage files
- shell tool installer for nvm, Node 25, npm globals, SDKMAN, Java 25.0.2-amzn, rbenv, and Ruby

## Structure
- `stow/` — actual dotfiles, grouped by package
- `packages/` — package manifests for reinstalling apps
- `scripts/` — helper scripts
- `bootstrap.sh` — one-shot setup script

## Fresh install flow
1. Install base OS
2. Clone this repo
3. Run:
   ```bash
   ./bootstrap.sh --yes
   ```
   Or run individual stages:
   ```bash
   ./bootstrap.sh --packages --shell --link --apps
   ```
   To preview without changing anything:
   ```bash
   ./bootstrap.sh --dry-run
   ```
4. In bootstrap, the setup runs in this order:
   - repo packages: `common.txt` -> `hyprland.txt` -> `apps.txt` -> `aur.txt`
   - shell tools: `nvm` -> Node.js 25 -> npm globals -> `SDKMAN` -> Java `25.0.2-amzn` -> `rbenv` Ruby `3.4.9`
   - link configs into your home directory
   - vendor apps from `~/Nedlastinger`
5. Download vendor apps into `~/Nedlastinger`
   - **IntelliJ IDEA / Rider:** On each JetBrains product page, pick **Linux** and download the **`.tar.gz`** archive (not Toolbox unless you install that separately). Typical filenames: `ideaIU-*.tar.gz` or `ideaIC-*.tar.gz` for IDEA, `JetBrains.Rider-*.tar.gz` or `rider-*.tar.gz` for Rider. The installer unpacks to `~/.local/opt/jetbrains/<app>/current/` and wires `~/.local/bin` plus desktop entries to the native **`bin/idea`** / **`bin/rider`** launchers (falls back to `.sh` only if the native binary is missing).
6. Run:
   ```bash
   ./scripts/install-apps.sh --yes
   ```
   This installs all detected vendor apps without prompting.
   Without `--yes`, it opens categorized checklists with everything selected by default.
   If `whiptail` is missing, it falls back to a non-interactive install-all mode.
7. Reboot / log out and back in

## Download links
Run:
```bash
./scripts/install-apps.sh --list
```
Or open these directly (then choose **Linux → .tar.gz** on the page):
- IntelliJ IDEA: https://www.jetbrains.com/idea/download/?section=linux
- Rider: https://www.jetbrains.com/rider/download/?section=linux
- Cursor: https://www.cursor.com/downloads
- Raider.IO: https://raider.io/addon
- Archon: https://www.archon.gg/download?utm_source=header-cta-archon
- OpenRazer setup docs: https://openrazer.github.io/#download

Download the Linux archive/app image for each into `~/Nedlastinger`.

The installer supports categorized checklists for:
- System: Warp Terminal
- Development: IntelliJ IDEA, Rider, Cursor, GitKraken
- Gaming: Raider.IO, Archon, CurseForge

Everything is checked by default, and already installed apps are marked as such.

## Packages installed from repos
The repo also installs the desktop apps I actually used to install manually:
- `vivaldi`
- `discord`
- `lutris`
- `steam`
- `github-cli`
- `podman-desktop`
- `anyrun`
- `openrazer-daemon`
- `input-remapper`
- `google-chrome` via AUR if `yay` is available
- `warp-terminal` via local `pkg.tar.zst` in `~/Nedlastinger`

## Tartarus V2 input remap setup
For Razer Tartarus key remaps, use `input-remapper` (not OpenRazer).

1. Install packages:
   ```bash
   ./bootstrap.sh --packages
   ```
2. Run the setup helper (defaults to your Tartarus id `1532:022B`):
   ```bash
   ./scripts/setup-input-remapper.sh
   ```
   Optional args:
   ```bash
   ./scripts/setup-input-remapper.sh 1532:022B tartarus
   ```
3. Create/save the preset in `input-remapper-gtk` with the same preset name (default: `tartarus`).
4. Trigger autoload once:
   ```bash
   input-remapper-control --command autoload
   ```

Config to keep in dotfiles:
- `~/.config/input-remapper-2/config.json`
- `~/.config/input-remapper-2/presets/`

## Notes
- If you add secrets later, keep them out of git.
- Secret-bearing local files are intentionally excluded, including `~/.config/gh/hosts.yml`.
- Browser/app profile data and caches are intentionally not tracked.
- The Hyprland polkit rule in `stow/hypr/.config/hypr/polkit/49-sddm-switch-user.rules` is intentional, but it is security-sensitive; review it before applying it on another machine.
- The repo is designed to be extended over time.
- If you want a machine-specific config, add a separate package or script.
- `packages/local-installs.md` lists local non-pacman installs like Warp Terminal.
- `kitty` has no config file in your current setup, so it is not included yet.
- run `./scripts/install-shell-tools.sh` if you want nvm + Node + SDKMAN + Java + rbenv Ruby without going through bootstrap.
- nvm installs to `~/.config/nvm` on this setup.
- Node.js 25 is installed by default after nvm.
- global npm packages are listed in `packages/npm-global.txt`.
- `rbenv` and `ruby-build` are installed from repo packages, and `./scripts/install-shell-tools.sh` installs Ruby `3.4.9` by default.
- To install the newest stable Ruby instead, run `RUBY_VERSION=latest ./scripts/install-shell-tools.sh`.
- `bootstrap.sh --yes` runs all stages without prompts.
- `bootstrap.sh --dry-run` prints the planned actions without changing anything.
