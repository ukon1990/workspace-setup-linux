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
- wofi / lxqt session config (Linux)
- package lists for reinstalling apps on a fresh system
- vendor app installer for downloaded tar.gz/AppImage files (Linux)
- shell tool installer for nvm, Node 25, npm globals, SDKMAN, Java 25.0.2-amzn, rbenv, and Ruby
- theme CLI under `stow/themes` (see `stow/themes/.config/themes/README.md`)
- Waybar widgets + NetHogs setup via `scripts/setup-network-usage.sh`
- day-to-day helpers under the stow `scripts` package (`closeports`, `gh-delete-all-artifact`, …)
- a read-only Jira/GitHub task browser (`tasks`)

## Structure
- `stow/` — actual dotfiles, grouped by package
- `packages/` — package manifests for reinstalling apps
- `scripts/` — repo/bootstrap helpers (run as `./scripts/...` from the clone)
- `stow/scripts/` — stow package linked to `~/scripts` for day-to-day commands
- `bootstrap.sh` — OS router (Linux → `bootstrap-linux.sh`, macOS → `bootstrap-macos.sh`)

## Stow packages by OS
- **Shared** (`packages/stow-shared.txt`): `nvim`, `fish`, `zsh`, `gh`, `scripts`
- **Linux only** (`packages/stow-linux.txt`): `hypr`, `waybar`, `lxqt`, `themes`, `cursor`

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
- repo packages: `common.txt` -> `hyprland.txt` -> `apps.txt` -> `aur.txt` -> `flatpak.txt`
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
through its `__main__.py`. The package is split into `bundles`, `cli`,
`common`, `desktop`, `icons`, `installation`, `management`, `metadata`, and
`registry` helpers. The command name remains `app-install`; Python source
files use `.py` extensions.

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
python3 -m unittest discover -s stow/scripts/scripts/gh-delete-all-artifact/tests -v
python3 -m unittest discover -s stow/themes/.config/themes/tests -v
python3 -m unittest discover -s stow/waybar/.config/waybar/scripts/tests -v
```

## Jira and GitHub task browser

`tasks` is a read-only Textual browser. Run `tasks` to choose GitHub or Jira
from a TUI menu. The most recently opened backend is highlighted at the top;
press Enter to reopen it, arrows or `j`/`k` to choose, or Esc/`q` to cancel.
Choosing Jira prompts for a project key when none is supplied or configured.
The choice is remembered globally in `~/.local/state/tasks/launcher.yaml`,
including launches with explicit flags.

Use a backend flag to skip the menu (required outside an interactive terminal):

```bash
tasks
tasks --jira --project PROJ
tasks --jira PROJ-123
tasks --jira https://example.atlassian.net/browse/PROJ-123
tasks --gh
tasks --gh 123
tasks --gh owner/repo#123
tasks --gh https://github.com/owner/repo/issues/123
tasks --gh --repo owner/repo --query "parser bug"
```

GitHub uses the current checkout unless `--repo` or a configured default is
provided. Jira list mode needs `--project` or a configured default. `--query`
starts a backend search; `--jql-extra` adds Jira filtering and `--search` adds
GitHub search qualifiers. Direct keys, numbers, qualified references, and issue
URLs open the issue immediately.

Configuration defaults to `~/.config/tasks/config.yaml` and can be overridden
with `--config`:

```yaml
jira:
  default_project: PROJ
  limit: 100
  jql_extra: 'labels = "ready"'
github:
  default_repo: owner/repo
  limit: 100
  search: "label:ready"
```

Supported keys are `jira.default_project`, `jira.limit`, `jira.jql_extra`,
`github.default_repo`, `github.limit`, and `github.search`. Unknown or invalid
values are rejected.

In the task list, press `f` to filter by assignee:

- `a`: all issues
- `m`: assigned to me
- `u`: unassigned
- `o`: assigned to me or unassigned
- `d`: assigned to anyone

Press `w` to choose which work to show in either table or tree view:

- **All** keeps all matching issues, including completed work.
- **Available** shows ready issues and unfinished ancestors with ready descendants.
- **Ready only** shows a compact list of ready issues; tree nodes attach to the nearest retained ancestor or become roots.

An unfinished issue (including in-progress work) is ready when it and its
ancestors have no unfinished explicit blockers. Completed blockers are ignored.
Unresolved dependency information is **Unknown** and does not count as ready.
The **Work** and **Ready descendants** table columns are sortable; tree labels
show the same information. Descendant counts exclude the parent and respect
assignee, backend search, and local text filters. Counts cover loaded matching
issues and may be partial when the configured limit is reached. Completion
progress in the tree is calculated before work branches are hidden.

Assignee and work filters are restored separately for each Jira project and
GitHub repository. `c` clears both active filters and that scope's saved choices.
State is stored at `~/.local/state/tasks/filters.yaml`. The `/` free-text filter
remains local to the current session and is not persisted. The status bar shows
the work mode, ready count, and any unknown or partial results. Refresh with `r`
to fetch changed issues and update blocker statuses; `R` resets the selected
project or repository cache and loads it again.
Work filters apply only to issues; pull-request browsing is unchanged.

In issue details, every relationship-tree issue has a completion icon: `✓`
completed, `○` unfinished (including in progress), or `?` unknown. Completed
links remain visible. Press `r` to sync changed issues and refresh linked statuses; unavailable targets
or links beyond the 80 additional-lookup limit show `?`.

Issue lists and loaded descriptions, comments, parents, and dependencies are
persisted per Jira project or GitHub repository under
`~/.local/state/tasks/cache`. The detail cache keeps the 200 most recently used
issues per scope. On opening an issue scope, the browser syncs backend changes
before displaying cached data, including issues outside the current filters.
Startup and `r` use paginated incremental updates with a five-minute overlap
around the last successful sync. Unchanged cached issues are reused without
refetching every relationship. `R` clears only the selected scope and rebuilds
it. Failed syncs keep cached data visible with a status-bar warning.

The sortable **Changed** column marks changed issue versions with `*`; overview
and detail-tree issue keys carry the same marker. Markers stay for the current
session. The first sync establishes a baseline and does not mark every issue
as changed. Opening a relationship in another project or repository syncs that
target scope before loading its detail.

Use `s` for a fresh backend search, `j`/`k` or arrows to move, `Enter` to open,
`Tab` to focus relationships, `o` to open the task URL in a browser, `?` for
help, `h` / Backspace / Esc to go back, `r` to refresh, and `q` to quit.

The dedicated PyYAML + Textual runtime is created automatically by the shared
shell-tool bootstrap, or manually with:

```bash
~/scripts/tasks-setup.sh
```

The command never installs backend CLIs and never writes to Jira or GitHub.
Install/authenticate GitHub CLI with `brew install gh` (macOS) or
`sudo pacman -S github-cli` (Arch), then `gh auth login`. Install Atlassian CLI
from Atlassian's official instructions (`brew tap atlassian/homebrew-acli &&
brew install acli` on macOS), then run `acli jira auth login`.

Run its tests and checks with:

```bash
PYTHONPATH=stow/scripts/scripts python3 -m unittest discover -s stow/scripts/scripts/tasks/tests -v
ruff check stow/scripts/scripts/tasks
bash -n stow/scripts/scripts/tasks.sh stow/scripts/scripts/tasks-setup.sh scripts/install-shell-tools.sh
```

## Disk mounting (Linux)

Launch the Textual disk browser as your normal user:

```bash
~/scripts/disks-setup.sh
disks
```

The `disks` command is supplied by the scripts Stow package; `~/scripts/disks.sh`
also works. Before linking, use `./stow/scripts/scripts/disks.sh` from this repo.
Linux shell-tool bootstrap installs its dedicated Textual runtime automatically;
macOS skips it. `DISKS_VENV` overrides `~/.local/share/disks/venv` for both setup
and launch. Linux package bootstrap includes Python/pip, util-linux, sudo, and
systemd. NTFS support comes from the kernel's `ntfs3` driver, not `ntfs-3g`.

Use arrows or `j`/`k` to select a partition, `m` to mount, `u` to unmount,
`b` to enable/disable mounting at boot, `r` to refresh, and `q` to quit.
In dialogs, Tab/Shift+Tab or arrows move between controls. Left/Right moves the
cursor when the mount path input is focused. Enter or Space activates buttons
and switches; on a dropdown, they open its choices and arrows select one.
Escape cancels. Every operation has a review step.
Sudo prompts appear in the terminal only when an operation needs elevation.
Don't start the whole TUI with sudo.

New mount locations default to `/mnt/<partition-name>` and can be changed to
a directory below `/mnt`, `/media`, or `/run/media`. Existing fstab entries
retain their mount locations. System filesystems, their backing devices,
read-only devices, and unsupported filesystems are view-only. Snap loop devices
and zram are hidden. NTFS, FAT32, exFAT, ext4, XFS, and Btrfs are supported;
formatting, repair, encrypted-volume unlocking, and network mounts are not.

NTFS mounts use `ntfs3`; NTFS, FAT, and exFAT use `rw,uid=<your UID>,gid=<your GID>,dmask=000,fmask=111`
so every local user can read/write directories and files created with these
mounts. ext4/XFS/Btrfs retain their existing Unix permissions. The browser
shows the actual mount options and whether your account has access to the mount
root. A read/write mount can still have a root directory without write permission.
After a manual NTFS mount, `disks` checks the root and, if needed, sets its mode
to 777 as disclosed in the review. Boot setup can make the same repair when the
NTFS drive is already mounted; otherwise mount it through `disks` once to check
the root. Existing files and subdirectories are never changed recursively, so
their permissions may still restrict access. A dirty/hibernated Windows volume
is never force-mounted or repaired: fully shut down Windows and resolve its
filesystem errors there before retrying. For a dirty NTFS volume, run
`chkdsk X: /f` as an administrator in Windows, replacing `X` with its actual
drive letter. The kernel usually gives the specific mount refusal in
`sudo journalctl -k -n 50`.

Already-mounted partitions cannot be mounted again. To change an existing
NTFS mount's ownership, unmount it and then mount it through the browser.
For stacked mounts, select the visible top layer (identified by mount ID),
unmount, refresh, and repeat as necessary. Busy mounts report the error;
the tool does not force or lazily unmount them.

Boot setup previews an exact fstab diff and uses UUIDs for new entries.
Enabled entries use `nofail,x-systemd.device-timeout=5s`; missing disks won't
block boot. The numeric UID/GID are saved for NTFS/FAT/exFAT, so update the
entry if your account IDs change. Disabling sets `noauto` and removes fstab
automount/boot-target options. Other separately configured services can still
mount the disk. Boot edits do not mount or unmount anything immediately.

Every actual fstab change requires a timestamped backup in
`/etc/fstab.backups/`. The candidate is validated with `findmnt --verify`, then
installed atomically with the previous ownership/mode. Concurrent fstab edits
abort the operation. Existing invalid fstab entries must be fixed before
saving. Backups are kept indefinitely; a failed systemd reload reports the
saved backup path and the command to retry.

To restore, select the exact backup you want, inspect it, then replace the
example filename below with that backup's name:

```bash
sudo ls -lt /etc/fstab.backups/
sudo diff -u /etc/fstab /etc/fstab.backups/fstab.TIMESTAMP
sudo findmnt --verify --tab-file /etc/fstab.backups/fstab.TIMESTAMP
sudo cp -a --backup=numbered /etc/fstab /etc/fstab.backups/fstab.before-manual-restore
sudo cp -p /etc/fstab.backups/fstab.TIMESTAMP /etc/fstab
sudo systemctl daemon-reload
```

Restoring fstab does not change currently mounted filesystems. Tests use
temporary fstab files and mocked privileged operations, never your real disks:

```bash
PYTHONPATH=stow/scripts/scripts ~/.local/share/disks/venv/bin/python -m unittest discover -s stow/scripts/scripts/disks/tests -v
ruff check stow/scripts/scripts/disks
ruff format --check stow/scripts/scripts/disks
bash -n stow/scripts/scripts/disks.sh stow/scripts/scripts/disks-setup.sh scripts/install-shell-tools.sh
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
- System + Development: Warp Terminal, IntelliJ IDEA, Rider, Cursor, GitKraken
- Gaming: Raider.IO, Archon, CurseForge

Everything is checked by default, and already installed apps are marked as such.

## Packages installed from repos
The repo also installs the desktop apps I actually used to install manually:
- `vivaldi`
- `discord`
- `lutris`
- `steam`
- `github-cli`
- `podman`
- `podman-desktop`
- `anyrun`
- `openrazer-daemon`
- `input-remapper`
- `kepler`
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
- Neovim config lives in `stow/nvim` and is linked on both OSes; see `stow/nvim/.config/nvim/README.md` for its architecture, keybindings, and verification workflow.
- `packages/local-installs.md` lists local non-pacman installs like Warp Terminal.
- `kitty` has no config file in your current setup, so it is not included yet.
- `stow/mako/` is an empty leftover and is not linked; mako config is generated by the theme CLI.
- run `./scripts/install-shell-tools.sh` if you want nvm + Node + SDKMAN + Java + rbenv Ruby without going through bootstrap.
- On macOS, run `./scripts/install-brew-packages.sh` for Homebrew formulas only.
- nvm installs to `~/.config/nvm` on this setup.
- Node.js 25 is installed by default after nvm.
- global npm packages are listed in `packages/npm-global.txt`.
- `rbenv` and `ruby-build` come from Linux repo packages or Homebrew; `./scripts/install-shell-tools.sh` installs Ruby `3.4.9` by default.
- To install the newest stable Ruby instead, run `RUBY_VERSION=latest ./scripts/install-shell-tools.sh`.
- `bootstrap.sh --yes` runs all stages without prompts (OS-appropriate set).
- `bootstrap.sh --dry-run` prints the planned actions without changing anything.

## Shell bootstrap and command availability

On macOS, `./bootstrap.sh` prepares compatible shell-tool dependencies before
running installers. `--shell` performs the same checks without requiring a prior
`--packages` run: Bash 4+ for SDKMAN, Python 3.12+ for the `tasks` runtime, and
rbenv with ruby-build for Ruby. Missing dependencies are installed with Homebrew;
installed Bash or Python formulas are upgraded only when their versions are too
old. Compatible existing tools are reused. `BASH_BIN` and `PYTHON_BIN` can select
specific executables; an incompatible explicit selection is reported rather than
silently replaced. Linux uses the same checks with dependencies from its package
lists.

Bootstrap refreshes its own environment automatically and uses the verified Bash
for SDKMAN and Python for runtime setup. A dependency problem skips the affected
tools while independent setup continues. Skips, installer failures, and linking
conflicts produce an incomplete report and exit status 2; resolve the reported
problem and rerun the relevant step.

`--link` links the existing command launchers into `~/.local/bin` and configures
Zsh to load `~/.config/workspace-setup/zsh-init.zsh`. Existing `.zshrc` and
`.zprofile` settings are preserved, with bootstrap-owned additions between
`# start workspace-setup` and `# end workspace-setup`. Reruns update that block
without duplicating it. Existing user files are backed up next to the original as
`<filename>.workspace-setup.bak` before their first modification. `ZDOTDIR` is
respected. The repository's `.zshrc` remains a compatibility loader for older
symlink-based installations; new Stow and restow passes leave user startup files
under bootstrap's management.

Homebrew initialization is persisted in `.zprofile` using its detected location
on Apple Silicon or Intel. The shared Zsh initialization makes `tasks` and
`restow` available through `~/.local/bin`, and initializes available nvm, SDKMAN,
and rbenv installations. `disks` is a Linux tool. Helpers exposed only through
Fish functions retain their existing behavior.

After bootstrap completes, open a new terminal or run `exec zsh -l` to refresh
your existing terminal. To repair command links and startup configuration, rerun
`./bootstrap.sh --link`. `--dry-run` prints intended changes without installing
packages, editing startup files, or creating links.

Focused verification:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_shell_*.py' -v
```
