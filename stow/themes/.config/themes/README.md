# Unified Hypr Themes

A small theme system that keeps **Hyprland**, **Waybar**, and **Mako** in sync
from a single palette definition. One command (or one click in the bar)
swaps colors across all three.

## Directory layout

```
~/.config/themes/
├── README.md
├── palettes/                   # theme definitions (source of truth)
│   ├── amber-dark.json
│   ├── paper-light.json
│   ├── rainbow.json
│   ├── slate-dark.json
│   ├── solarized-dark.json
│   └── solarized-light.json
├── bin/
│   ├── theme                   # main CLI (Python)
│   ├── set-theme               # convenience wrapper: `theme set ...`
│   └── theme-from-wallpaper    # optional: generate a palette from an image
└── state/
    └── current                 # last applied theme name (auto-managed)
```

Generated files (rewritten every time a theme is applied):

- `~/.config/hypr/theme.conf` — sourced from `hyprland.conf`
- `~/.config/waybar/colors.css` — imported from `waybar/style.css`
- `~/.config/mako/config` — full mako config (regenerated in place)

Do **not** hand-edit the generated files — they will be overwritten on the
next theme switch. Change palette JSON or the generator in `bin/theme`
instead.

## Quick start

Add `~/.config/themes/bin` to your `PATH`. For fish:

```fish
fish_add_path ~/.config/themes/bin
```

Then use the short commands:

```fish
set-theme solarized-dark      # apply a named theme
theme list                    # list available themes (* marks current)
theme current                 # print active theme name
theme cycle                   # next theme
theme cycle --backward        # previous theme
theme picker                  # open wofi/fuzzel/rofi/bemenu picker
theme apply                   # regenerate files for the current theme
```

If the binary directory isn't on `PATH`, call it with the full path:

```fish
~/.config/themes/bin/theme set amber-dark
```

## Waybar widget

A `custom/theme` module lives in `~/.config/waybar/config.jsonc`. It
behaves like a dropdown: left-click pops a theme list anchored to the
top-right corner (where the widget sits), and the other actions let you
cycle without opening a menu.

- **Left click** — open dropdown picker (auto-positioned to top-right;
  auto-detects `wofi`, `fuzzel`, `rofi`, or `bemenu`; falls back to
  cycling forward if none are installed)
- **Right click** — next theme
- **Middle click** — previous theme
- **Scroll up / down** — cycle themes
- **Tooltip** — shows the current theme and every available option

The widget JSON is produced by `theme widget` and polled every 5 seconds.
Its CSS class reflects the theme mode (`theme-light` / `theme-dark`) and
the theme name (`theme-amber-dark`, etc), so you can target specific
themes in `waybar/style.css` if you want per-theme tweaks.

## System light / dark integration

Every time the theme changes, the manager also tells the rest of the
system whether you're in dark or light mode via:

```
gsettings set org.gnome.desktop.interface color-scheme prefer-dark
gsettings set org.gnome.desktop.interface color-scheme prefer-light
```

It also updates the legacy `gtk-application-prefer-dark-theme` key for
older GTK apps that still read it.

Apps that pick this up automatically:

- GTK 4 apps (via libadwaita `color-scheme`)
- Anything using the XDG Desktop Portal's appearance service
  (most Electron apps including Cursor / VS Code, Chromium, Vivaldi,
  Firefox with `widget.use-system-colors` / `layout.css.prefers-color-scheme.content-override`)
- Modern Qt 6 apps with `QT_QPA_PLATFORMTHEME=gnome`

Apps that **don't** pick it up automatically usually just need a flag
in their own settings (for example Vivaldi has
Settings → Themes → "Use system appearance").

The manager does **not** touch the GTK theme name (`gtk-theme` /
`icon-theme`) — only the color-scheme preference — so it won't
clobber the theme you've already picked in `gtkrc` / `gtk-4.0`.

## Commands in detail

### `theme set <name>`

Applies a named theme:

1. Renders `hypr/theme.conf`, `waybar/colors.css`, and `mako/config`
   from the palette.
2. Writes the new theme name to `state/current`.
3. Reloads Hyprland (`hyprctl reload`), Waybar (`pkill -SIGUSR2
   waybar`), and Mako (`makoctl reload`).
4. Updates the system color-scheme preference via `gsettings` so GTK,
   Electron, and portal-aware apps switch to light or dark mode with you
   (see "System light / dark integration" above).

Flags:

- `--no-reload` — just regenerate files, don't reload services or touch
  the system color-scheme preference.
- `-q`, `--quiet` — suppress per-service reload messages.

### `theme cycle [--backward]`

Picks the next (or previous) palette alphabetically from `palettes/`
and applies it. Wired to the Waybar widget's right-click, middle-click,
and scroll-wheel actions.

### `theme picker`

Opens a dmenu-style picker with all palettes, positioned as a dropdown
at the top-right. The first available tool wins: `wofi` → `fuzzel` →
`rofi` → `bemenu`. If none are installed, falls back to `theme cycle`
(forward). Wired to the Waybar widget's left-click action.

### `theme widget`

Prints one-line JSON for Waybar's custom module. Not intended for
interactive use.

### `theme apply`

Regenerates files for the currently saved theme without changing which
theme is active. Useful after you edit a palette JSON or tweak the
generator.

### `theme list` and `theme current`

Informational. `list` marks the active theme with `*`.

## Adding a new theme

Create `~/.config/themes/palettes/<name>.json` with these keys:

```json
{
    "name": "my-theme",
    "display_name": "My Theme",
    "mode": "dark",
    "icon": "\uf186",
    "colors": {
        "bg": "#0f0e0c",
        "surface": "#161412",
        "surface_high": "#211d19",
        "surface_higher": "#2c2621",
        "outline": "#4a3d31",
        "text": "#eee1cc",
        "text_muted": "#c8b79f",
        "primary": "#cb7e2c",
        "primary_container": "#5a3815",
        "on_primary": "#fff1de",
        "accent_container": "#6f431a",
        "hypr_active_border": "#c97a2b",
        "hypr_inactive_border": "#3a3028",
        "shadow": "#1a1a1a",
        "groupbar_active": "#5a3815",
        "groupbar_inactive": "#1a1714",
        "groupbar_locked_active": "#7a4a1f",
        "groupbar_locked_inactive": "#2b2520",
        "groupbar_text_active": "#f2e8d8",
        "groupbar_text_inactive": "#c7b79d"
    }
}
```

Field notes:

- `name` must match the filename (without `.json`).
- `mode` is `"dark"` or `"light"`. Light mode uses `Papirus-Light`
  icons in Mako and enables the `theme-light` class in Waybar.
- `icon` is a Nerd Font glyph shown in the Waybar theme widget.
  Defaults to a moon (dark) / sun (light) in the supplied palettes.
- All `colors.*` entries must be `#RRGGBB` hex. Alpha is applied by
  the generator per token.

After adding the file, test with:

```fish
theme set my-theme
```

### Palette token reference

| Token | Purpose |
|---|---|
| `bg` | Hardest background color. Empty workspace bg, Mako low-urgency bg. |
| `surface` | Panel / pill background (Waybar modules, Mako normal). |
| `surface_high` | Raised surface (tooltips, Mako high-urgency bg). |
| `surface_higher` | Interactive hover surface. |
| `outline` | Base border color (used at 55% and 90% alpha). |
| `text` | Primary text color. |
| `text_muted` | Secondary text (used at 100%, 68%, 45% alpha). |
| `primary` | Accent color (active borders, idle inhibitor, volume active). |
| `primary_container` | Filled accent background (active workspace, active idle inhibitor). |
| `on_primary` | Readable text on top of `primary_container`. |
| `accent_container` | Attention accent (Waybar tray needs-attention, Mako alt). |
| `hypr_active_border` / `hypr_inactive_border` | Hyprland window borders. |
| `shadow` | Hyprland window shadow color. |
| `groupbar_*` | Hyprland groupbar colors (tabs-within-windows UI). |

## Wallpaper-derived theme (optional)

```fish
theme-from-wallpaper ~/Pictures/wallpaper.jpg
```

Writes `palettes/wallpaper.json` and applies it immediately. The helper
tries these sources in order:

1. **`matugen`** (recommended) — Material You-style palette generation.
   If installed, produces rich coordinated colors.
2. **Pillow fallback** — uses `python-pillow` to pick a dominant color
   from the image and tints the token set around it.

Install either for best results:

```fish
# Arch / CachyOS
yay -S matugen-bin       # or pip install matugen
pacman -S python-pillow  # fallback
```

Flags:

- `--no-apply` — only write the palette, don't switch to it.

The generated `wallpaper` theme shows up in `theme list` like any other.
Rerun `theme-from-wallpaper` to refresh it when you change wallpapers.

## Editing the generator

`bin/theme` is a single Python 3 script with no external dependencies
(stdlib only). Key functions:

- `render_hypr(palette)` → content of `hypr/theme.conf`
- `render_waybar(palette)` → content of `waybar/colors.css`
- `render_mako(palette)` → content of `mako/config`

Alpha values for each token are encoded here (not in palette JSON), so
the glass/transparency look is consistent across themes. Tweak those
constants if you want a more or less translucent UI.

After changes, re-render for the current theme:

```fish
theme apply
```

## Troubleshooting

**`set-theme: command not found`**
Your `PATH` is missing `~/.config/themes/bin`. See Quick start above.

**Waybar widget stays blank after switching**
Restart Waybar manually once:

```fish
pkill -SIGUSR2 waybar
```

or

```fish
pkill waybar; waybar &
```

**Hyprland colors don't change**
Make sure `hyprland.conf` contains the `source = ~/.config/hypr/theme.conf`
line near the top. Then run `hyprctl reload`.

**Mako doesn't pick up changes**
`makoctl reload` must be run inside your Wayland session (it needs
user D-Bus). Running it from a sandboxed context will fail with
`sd_bus_open_user() failed`.

**Picker doesn't open**
Install any of `wofi`, `fuzzel`, `rofi`, or `bemenu`. Without one,
left-clicking the widget falls back to cycling forward.

**Apps don't follow system light/dark switch**
Run `gsettings get org.gnome.desktop.interface color-scheme` to confirm
the preference is being set. If it is but an app still ignores it, the
app usually has its own "Follow system" toggle (Vivaldi, Firefox, some
KDE/Qt apps). Qt 6 apps also need `QT_QPA_PLATFORMTHEME=gnome` in your
environment to read the GNOME setting.

**`gsettings` not installed**
On CachyOS / Arch:

```fish
sudo pacman -S glib2
```

Without `gsettings` the color-scheme sync step is skipped silently; the
visual theme still switches normally.

**Reverting an edit to a generated file**
Just run `theme apply` — it overwrites the generated files from the
active palette.
