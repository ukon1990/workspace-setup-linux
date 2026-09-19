# Neovim configuration guidance

These instructions apply to everything under `stow/nvim/`.

## Supported environment

- Target Neovim 0.12.x on both macOS and Linux.
- Keep the configuration portable across both operating systems. Guard platform-specific executables and APIs.
- Use the existing Lazy.nvim, Snacks, Overseer, neotest, Mason, LSP, DAP, lint, and formatting stack before adding dependencies.
- Do not add a plugin merely to replace functionality already supplied by Neovim or an installed plugin.

## Architecture invariants

- `config.tool_panel` owns tool-window layout. Do not open independent persistent task/test splits around it.
- Keep one right activity rail per tabpage. It switches between Overseer Tasks and the neotest Summary.
- Keep build and test logs in the shared bottom output dock. Starting a task or test must not steal editor focus.
- Tool-panel state and output history must remain isolated per tabpage and recover after `WinClosed` or `TabClosed`.
- Tool trees use one screen row per item: no wrapping, an `extends:…` marker, and horizontal scrolling.
- Normal code buffers do not wrap. Markdown and Git commit buffers intentionally use soft wrapping.
- `project_tools` discovery is repository-cached and path-contextual. New project markers must be added to cache invalidation as well as discovery.
- Custom Overseer build/test templates should attach the appropriate parser from `config.task_errors` and retain the `default` component alias.
- Background task errors populate quickfix without opening or focusing it. `<leader>xq` is the user-facing error picker.

## Performance rules

- Do not eagerly load DAP, neotest, Overseer, language-specific tooling, or Mason UI code.
- A no-file startup should load only the essential UI/runtime plugins and remain below 130 ms on the reference machine.
- Avoid recursive filesystem scans or full buffer/window scans on frequently fired autocmds.
- Avoid duplicate language tooling. Angular workspaces use `angularls` instead of `ts_ls`; `eslint_d` is only a fallback when the ESLint LSP is absent.

## Required verification

Run these checks after relevant changes from the repository root:

```sh
find stow/nvim/.config/nvim -name '*.lua' -print0 | xargs -0 -n1 luac -p
XDG_STATE_HOME=/tmp/nvim-state XDG_CACHE_HOME=/tmp/nvim-cache \
  nvim --headless -i NONE \
  -u "$PWD/stow/nvim/.config/nvim/init.lua" \
  "+luafile $PWD/stow/nvim/.config/nvim/tests/headless.lua" +qa
git diff --check
```

For load-time changes, also record `--startuptime` and verify that `nvim-dap`, `neotest`, and `overseer.nvim` are not loaded at `VimEnter` unless explicitly invoked.

Preserve unrelated staged and unstaged work. Follow the existing two-space Lua indentation; this repository does not currently carry a StyLua configuration.
