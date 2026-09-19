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
| `<leader>Td` | Run every suite beneath the selected Explorer/current-buffer directory |
| `<leader>Ts` | Toggle Tests in the activity rail |
| `<leader>ro` | Focus the latest task output |
| `<leader>r[` / `<leader>r]` | Previous/next output tab |
| `<leader>rv` | Show two output tabs side by side |
| `<leader>tt` | Toggle terminal as a bottom-dock tab (same group as runners) |
| `<leader>tv` / `<leader>th` | Terminal in a right/left editor split |
| `<leader>ts` | Terminal stacked in a second bottom split |
| `<leader>xq` | Open parsed task errors |
| `[q` / `]q` | Previous/next task error |
| `<leader>xx` | Workspace diagnostics |
| `<leader>xX` | Current-buffer diagnostics |

Use `<S-h>` and `<S-l>` inside the output dock to switch its tabs. Narrow task/test trees do not wrap; scroll horizontally to reveal clipped text.

Pressing `r` on a Tests Summary folder reuses that folder's output slot, replacing the previous output. An active suite is stopped and its results finish processing before the replacement starts; rapid reruns keep only the latest request. Ownership includes the full selected folder path, full adapter identity, and originating tabpage—not the runner's working directory or display label. Other folders/adapters/tabs remain independent, and background output never changes keyboard focus. Adapters producing multiple execution specs retain a separate slot for each spec. The same behavior applies to directory/suite shortcuts and Run last; individual tests, debug runs, and the aggregate output panel keep their existing behavior.

`<leader>Ta` / `<leader>Tu` seed Maven, Gradle, and npm roots that actually declare a runner (Vitest/Jest/react-scripts), keep a Tests-rail loading state until expected adapters (e.g. `neotest-maven · backend` and `neotest-vitest · frontend`) have non-empty trees, then stack those suites in the rail. Nested packages under a Vitest root (e.g. `frontend/ethereal-ui`) stay on Vitest. Suite runs use Overseer so each runner gets its own bottom-dock tab (`tests: backend`, `tests: frontend`). `<leader>tt` opens the shell in that same dock tab group. `<leader>Td` narrows suite runs to the Explorer/current-buffer directory. Maven Java/Kotlin uses `./mvnw`; Gradle uses `neotest-gradle`. Rust only activates in Cargo projects. Summary jumps reuse a normal editor window.

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
