return {
  {
    "folke/snacks.nvim",
    priority = 1000,
    lazy = false,
    opts = {
      bigfile = { enabled = true },
      notifier = { enabled = true },
      quickfile = { enabled = true },
      statuscolumn = { enabled = true },
      words = { enabled = true },
      input = { enabled = true },
      explorer = { enabled = true },
      picker = {
        enabled = true,
        sources = {
          explorer = {
            hidden = true,
            actions = {
              -- Open as a winbuf tab in the focused editor (not a Neovim tabpage —
              -- tabpages hide the explorer and can spawn a second kotlin_lsp).
              explorer_open_tab = function(picker)
                Snacks.picker.actions.jump(picker, nil, { cmd = "edit" })
              end,
              explorer_open_vsplit_left = function(picker)
                local prev = vim.o.splitright
                vim.o.splitright = false
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "vsplit" })
                vim.o.splitright = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_vsplit_right = function(picker)
                local prev = vim.o.splitright
                vim.o.splitright = true
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "vsplit" })
                vim.o.splitright = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_hsplit_up = function(picker)
                local prev = vim.o.splitbelow
                vim.o.splitbelow = false
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "split" })
                vim.o.splitbelow = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_hsplit_down = function(picker)
                local prev = vim.o.splitbelow
                vim.o.splitbelow = true
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "split" })
                vim.o.splitbelow = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_menu = function(picker)
                local mp = vim.fn.getmousepos()
                if mp.winid == picker.list.win.win then
                  local idx = picker.list:row2idx(mp.line)
                  if idx and idx > 0 then
                    picker.list:view(idx)
                  end
                end

                local item = picker:current()
                if not item or item.dir then
                  return
                end

                local choices = {
                  { label = "Open in editor tab", action = "explorer_open_tab" },
                  { label = "Open split left", action = "explorer_open_vsplit_left" },
                  { label = "Open split right", action = "explorer_open_vsplit_right" },
                  { label = "Open split up", action = "explorer_open_hsplit_up" },
                  { label = "Open split down", action = "explorer_open_hsplit_down" },
                }
                vim.ui.select(choices, {
                  prompt = "Open file",
                  format_item = function(choice)
                    return choice.label
                  end,
                }, function(choice)
                  if choice then
                    picker:action(choice.action)
                  end
                end)
              end,
            },
            win = {
              list = {
                keys = {
                  ["<RightMouse>"] = "explorer_open_menu",
                },
              },
            },
          },
        },
      },
      terminal = { enabled = true },
    },
    keys = {
      {
        "<leader>ff",
        function()
          Snacks.picker.files()
        end,
        desc = "Find files",
      },
      {
        "<leader>fg",
        function()
          Snacks.picker.grep()
        end,
        desc = "Grep",
      },
      {
        "<leader>fb",
        function()
          Snacks.picker.buffers()
        end,
        desc = "Buffers",
      },
      {
        "<leader>fh",
        function()
          Snacks.picker.help()
        end,
        desc = "Help pages",
      },
      {
        "<leader>fr",
        function()
          Snacks.picker.recent()
        end,
        desc = "Recent files",
      },
      {
        "<leader>fe",
        function()
          Snacks.explorer()
        end,
        desc = "File explorer",
      },
      {
        "<leader>e",
        function()
          Snacks.explorer()
        end,
        desc = "File explorer",
      },
      {
        "<leader>gg",
        function()
          if vim.fn.executable("lazygit") ~= 1 then
            vim.notify(
              "lazygit is not installed. Install it (e.g. `paru -S lazygit`) then retry.",
              vim.log.levels.WARN,
              { title = "Snacks" }
            )
            return
          end
          Snacks.lazygit()
        end,
        desc = "Lazygit",
      },
      {
        "<leader>n",
        function()
          Snacks.notifier.show_history()
        end,
        desc = "Notification history",
      },
      {
        "<leader>tt",
        function()
          Snacks.terminal()
        end,
        desc = "Toggle terminal",
      },
      {
        "<leader>uN",
        function()
          Snacks.notifier.hide()
        end,
        desc = "Dismiss notifications",
      },
      {
        "<leader>fd",
        function()
          Snacks.picker.diagnostics()
        end,
        desc = "Diagnostics",
      },
      {
        "<leader>fs",
        function()
          Snacks.picker.lsp_symbols()
        end,
        desc = "LSP symbols",
      },
      {
        "<leader>fk",
        function()
          Snacks.picker.keymaps()
        end,
        desc = "Search keymaps",
      },
      {
        "<C-:>",
        function()
          Snacks.picker.keymaps()
        end,
        desc = "Search keymaps",
        mode = { "n", "i", "v" },
      },
    },
  },
}
