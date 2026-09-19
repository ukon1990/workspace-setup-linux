# dotfiles

My workstation config repo.

This repo is meant to be **public-safe**:
- no secrets
- no SSH keys
- no tokens or private credentials
- no browser profiles or cache

## What lives here
- Hyprland / Waybar / theme stack (Linux)
- Neovim config (shared Linux + macOS)
- shell config (fish / zsh)
- gh config
- sherlock / lxqt session config (Linux)
- package lists for reinstalling apps on a fresh system
- vendor app installer for downloaded tar.gz/AppImage files (Linux)
- shell tool installer for nvm, Node 25, npm globals, SDKMAN, Java 25.0.2-amzn, rbenv, and Ruby

## Structure
- `stow/` — actual dotfiles, grouped by package
- `packages/` — package manifests for reinstalling apps
- `scripts/` — helper scripts
- `bootstrap.sh` — OS router (Linux → `bootstrap-linux.sh`, macOS → `bootstrap-macos.sh`)

## Stow packages by OS
- **Shared** (`packages/stow-shared.txt`): `nvim`, `fish`, `zsh`, `gh`, `scripts`
- **Linux only** (`packages/stow-linux.txt`): `hypr`, `waybar`, `lxqt`, `sherlock`, `themes`, `cursor`

## Fresh install flow
1. Install base OS (Arch/CachyOS/… or macOS)
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

### Linux (`bootstrap-linux.sh`)
Order:
- repo packages: `common.txt` -> `hyprland.txt` -> `apps.txt` -> `aur.txt`
- shell tools: `nvm` -> Node.js 25 -> npm globals -> `SDKMAN` -> Java `25.0.2-amzn` -> `rbenv` Ruby `3.4.9`
- link shared + Linux-only configs
- vendor apps from `~/Nedlastinger`

Then download vendor apps into `~/Nedlastinger` and run:
```bash
./scripts/install-apps.sh --yes
```
- **IntelliJ IDEA / Rider:** On each JetBrains product page, pick **Linux** and download the **`.tar.gz`** archive (not Toolbox unless you install that separately). Typical filenames: `ideaIU-*.tar.gz` or `ideaIC-*.tar.gz` for IDEA, `JetBrains.Rider-*.tar.gz` or `rider-*.tar.gz` for Rider. The installer unpacks to `~/.local/opt/jetbrains/<app>/current/` and wires `~/.local/bin` plus desktop entries to the native **`bin/idea`** / **`bin/rider`** launchers (falls back to `.sh` only if the native binary is missing).
Without `--yes`, it opens categorized checklists with everything selected by default.
If `whiptail` is missing, it falls back to a non-interactive install-all mode.
Reboot / log out and back in when the desktop stack is ready.

### macOS (`bootstrap-macos.sh`)
Order:
- Homebrew formulas from `packages/brew.txt` and casks from `packages/brew-casks.txt` (e.g. `ollama-app`)
- Already-installed brew packages are skipped; optional install failures are reported and do not abort bootstrap (essential: `git`, `stow`, `curl`)
- shell tools: same `install-shell-tools.sh` as Linux
- link **shared** stow packages only (`--apps` is skipped on macOS)

## Install or update a downloaded app

After `restow scripts fish`, use `app-install` from Fish in any directory.
From another shell, use `~/scripts/app-install.sh` directly. The installer requires
Python 3.12 or newer; `.tar.zst` also requires `zstd`.

`app-install.sh` is a small Bash launcher that runs the `app_install` package
through its `__main__.py`. The package is split into CLI,
installation, app management, registry, archive, icon, and desktop helpers.
The command name remains `app-install`; Python source files use `.py` extensions.

```bash
app-install ./Something.AppImage
app-install ./Something-2.0.AppImage --name Something --icon ./something.svg
app-install ./Something-3.0.AppImage --update
app-install ./Something.tar.gz --name Something --exec bin/something
app-install ./Cursor.AppImage --name Cursor --password-store gnome-libsecret
app-install ./Something.AppImage --dry-run
app-install --rename Something --name Something-2.0
app-install --rename Something
app-install --uninstall
app-install --remove --name Something
app-install --list
app-install --edit --name Something --categories "Development;IDE;"
app-install --edit --categories "Game;"  # select an installed app
app-install --edit --name Cursor --password-store gnome-libsecret
```

- `--name` defaults to the filename without its extension. Use a stable name for
  versioned downloads: the same name updates the same app.
- `--update` selects an existing app of the same type, including installations
  made by `install-apps.sh`. It uses a dialog or numbered terminal menu. Supply
  `--name Something` with `--update` to select an existing app without prompting.
- Icons persist across updates. `--icon` explicitly replaces the saved icon;
  otherwise new installs try bundled icons and fall back to a generic icon.
- `--password-store` sets a Chromium/Electron keyring backend
  (`gnome-libsecret`, `gnome`, `kwallet5`, `kwallet6`, `kwallet`, or `basic`)
  injected into the launcher wrapper. Useful on Hyprland and other sessions
  where Electron cannot auto-detect an OS keyring. The value is stored in
  `app-install.json` and kept across updates unless you pass a new value.
  With `--edit`, an empty `--password-store ''` clears it and rewrites the
  wrapper without the flag.
- Tarball launchers are detected when unambiguous. Use `--exec` relative to the
  app root (after removing a single enclosing directory) when necessary.
- `--rename NEW_NAME` changes the display name and launcher command. Pass the
  current name with `--name`, or omit it to select an installed app. Icons and
  payload paths are preserved; future updates use the new name.
- `--list` (or `-l`) shows managed apps with their IDs, bundle types, and desktop
  categories. Optionally filter by `--name`.
- `--edit` updates desktop metadata without reinstalling. Supply `--name` or
  select an app interactively. Supported fields are `--categories`, `--comment`
  (description), `--keywords`, `--startup-class`, `--icon`,
  `--password-store`, and `--terminal` / `--no-terminal`. Categories and
  keywords use semicolon-separated lists; quote them in the shell. Empty
  strings clear text fields (and `--password-store`). Omitted fields remain
  unchanged, and `--dry-run` previews changes. Use `--rename` to change the
  app's name and command. Changing `--password-store` also rewrites the bin
  wrapper.
- `--uninstall` (alias `--remove`) lists all managed apps to choose from, or
  removes the app selected by `--name`. It removes the installation directory,
  including saved icons and previous releases, plus its command and desktop
  entry. Downloads, app settings outside the installation, and external symlink
  targets are retained. Rename and removal both support `--dry-run`.
- Supported files: AppImage, `.tar`, `.tar.gz`, `.tgz`, `.tar.xz`, `.tar.bz2`,
  and `.tar.zst`. These must be runnable app bundles, not source distributions.

Apps install under `~/.local/opt/apps`, with commands in `~/.local/bin` and
desktop entries in `~/.local/share/applications`. `INSTALL_ROOT`, `BIN_DIR`, and
`DESKTOP_DIR` override these locations. Existing JetBrains paths are preserved.
Source downloads are untouched. Previous payloads remain in the app directory
as `release-*` or `legacy-*`; they can be removed once no longer needed or running.
AppImage icon discovery runs the bundle's extraction command, so use trusted
downloads just as you would when launching an AppImage.

## Python formatting and linting

Install the pinned development tool in a local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Format all repository Python code and apply safe lint fixes:

```bash
./scripts/format-python.sh
```

Check without modifying files (also suitable for CI):

```bash
./scripts/format-python.sh --check
```

The script uses the local virtual environment's Ruff, falling back to `ruff` on
`PATH`. It always runs from the repository root and includes Python under hidden
Stow directories. Formatting, import sorting, and lint rules are configured in
`pyproject.toml`; remaining diagnostics must be fixed manually. Editors with
Ruff integration can use the same configuration for format-on-save.

Run the Python regression suites with:

```bash
python3 -m unittest discover -s scripts/tests -v
python3 -m unittest discover -s stow/waybar/.config/waybar/scripts/tests -v
```

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
- Neovim config lives in `stow/nvim` and is linked on both OSes.
- `packages/local-installs.md` lists local non-pacman installs like Warp Terminal.
- `kitty` has no config file in your current setup, so it is not included yet.
- run `./scripts/install-shell-tools.sh` if you want nvm + Node + SDKMAN + Java + rbenv Ruby without going through bootstrap.
- On macOS, run `./scripts/install-brew-packages.sh` for Homebrew formulas only.
- nvm installs to `~/.config/nvm` on this setup.
- Node.js 25 is installed by default after nvm.
- global npm packages are listed in `packages/npm-global.txt`.
- `rbenv` and `ruby-build` come from Linux repo packages or Homebrew; `./scripts/install-shell-tools.sh` installs Ruby `3.4.9` by default.
- To install the newest stable Ruby instead, run `RUBY_VERSION=latest ./scripts/install-shell-tools.sh`.
- `bootstrap.sh --yes` runs all stages without prompts (OS-appropriate set).
- `bootstrap.sh --dry-run` prints the planned actions without changing anything.
