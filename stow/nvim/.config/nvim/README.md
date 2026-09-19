# Neovim configuration

This is a portable Neovim 0.12 configuration for web, JVM/Kotlin, Java, Python, Go, Rust, .NET, Swift, and mobile development. It is installed through the repository's `stow/nvim` package.

## Structure

- `init.lua` loads options, keymaps, autocmds, and Lazy.nvim.
- `lua/plugins/` contains plugin specifications grouped by responsibility.
- `lua/config/tool_panel.lua` owns the Tasks/Tests activity rail and shared output dock.
- `lua/config/project_tools.lua` discovers monorepo workspaces and caches task metadata.
- `lua/config/task_errors.lua` defines compiler and linter output parsers.
- `lua/overseer/template/user/` contains project-aware task templates.
- `tests/headless.lua` covers layout, focus, cache, parser, and quickfix behavior.

## Tool layout

The layout intentionally uses stable regions:

```text
┌──────────┬──────────────────────────┬──────────────┐
│ Explorer │ Editor                   │ Tasks/Tests  │
│          │                          │ activity rail│
├──────────┴──────────────────────────┴──────────────┤
│ Shared build/test output tabs                      │
└────────────────────────────────────────────────────┘
```

Tasks and Tests share the right rail rather than creating competing splits. Build and test output buffers stay available as tabs in the bottom dock. Starting work updates these regions without moving keyboard focus from the editor.

## Main workflow keys

| Key | Action |
| --- | --- |
| `<leader>rr` | Select and run a task |
| `<leader>rt` | Toggle Tasks in the activity rail |
| `<leader>Ta` | Run all tests and show Tests in the rail |
| `<leader>Ts` | Toggle Tests in the activity rail |
| `<leader>ro` | Focus the latest task output |
| `<leader>r[` / `<leader>r]` | Previous/next output tab |
| `<leader>rv` | Show two output tabs side by side |
| `<leader>xq` | Open parsed task errors |
| `[q` / `]q` | Previous/next task error |
| `<leader>xx` | Workspace diagnostics |
| `<leader>xX` | Current-buffer diagnostics |

Use `<S-h>` and `<S-l>` inside the output dock to switch its tabs. Narrow task/test trees do not wrap; scroll horizontally to reveal clipped text.

## Task discovery and errors

Overseer discovers npm, Gradle/KMP/Android, Maven, .NET, Xcode, and Swift Package Manager projects. Discovery is cached by Git root and active path. `<leader>rc` clears both Overseer's template cache and the workspace cache.

Custom build tasks parse common compiler output into a task-scoped quickfix list. Failures notify without opening another pane; use `<leader>xq` when you want to inspect them.

## Verification

From the repository root:

```sh
find stow/nvim/.config/nvim -name '*.lua' -print0 | xargs -0 -n1 luac -p

XDG_STATE_HOME=/tmp/nvim-state XDG_CACHE_HOME=/tmp/nvim-cache \
  nvim --headless -i NONE \
  -u "$PWD/stow/nvim/.config/nvim/init.lua" \
  "+luafile $PWD/stow/nvim/.config/nvim/tests/headless.lua" +qa

git diff --check
```

Profile startup with:

```sh
XDG_STATE_HOME=/tmp/nvim-state XDG_CACHE_HOME=/tmp/nvim-cache \
  nvim --headless -i NONE \
  --startuptime /tmp/nvim-startup.log \
  -u "$PWD/stow/nvim/.config/nvim/init.lua" +qa
```

The current reference measurement is approximately 30 ms for a no-file startup. DAP, neotest, and Overseer should remain unloaded until requested.
