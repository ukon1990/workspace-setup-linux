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
      picker = { enabled = true },
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
