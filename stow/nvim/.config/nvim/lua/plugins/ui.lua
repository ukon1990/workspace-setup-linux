return {
  {
    "nvim-tree/nvim-web-devicons",
    lazy = true,
  },
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    opts = {
      preset = "modern",
      spec = {
        { "<leader>f", group = "find" },
        { "<leader>c", group = "code" },
        { "<leader>g", group = "git" },
        { "<leader>h", group = "hunks" },
        { "<leader>b", group = "buffer" },
        { "<leader>j", group = "java" },
        { "<leader>t", group = "terminal" },
        { "<leader>u", group = "ui" },
        { "<leader>x", group = "diagnostics" },
      },
    },
  },
  {
    "nvim-lualine/lualine.nvim",
    event = "VeryLazy",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    opts = {
      options = {
        theme = "tokyonight",
        globalstatus = true,
        component_separators = { left = "", right = "" },
        section_separators = { left = "", right = "" },
      },
      sections = {
        lualine_a = { "mode" },
        lualine_b = { "branch", "diff", "diagnostics" },
        lualine_c = { { "filename", path = 1 } },
        lualine_x = { "encoding", "fileformat", "filetype" },
        lualine_y = { "progress" },
        lualine_z = { "location" },
      },
    },
  },
  {
    "e-sigs/winbuf.nvim",
    event = "VeryLazy",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    opts = {
      style = "thin",
      hide_single = false,
      max_name_length = 48,
      truncate_names = true,
      diagnostics = "nvim_lsp",
      buf_delete = function(buf)
        Snacks.bufdelete(buf)
      end,
    },
    config = function(_, opts)
      require("winbuf").setup(opts)
      require("config.winbuf_fix").setup()
    end,
    keys = {
      {
        "<S-h>",
        function()
          require("winbuf").cycle(-1)
        end,
        desc = "Prev window buffer",
      },
      {
        "<S-l>",
        function()
          require("winbuf").cycle(1)
        end,
        desc = "Next window buffer",
      },
      {
        "<leader>bd",
        function()
          require("winbuf").close_buf()
        end,
        desc = "Close window buffer",
      },
    },
  },
  {
    "folke/todo-comments.nvim",
    event = { "BufReadPost", "BufNewFile" },
    dependencies = { "nvim-lua/plenary.nvim" },
    opts = {},
    keys = {
      {
        "]t",
        function()
          require("todo-comments").jump_next()
        end,
        desc = "Next todo comment",
      },
      {
        "[t",
        function()
          require("todo-comments").jump_prev()
        end,
        desc = "Previous todo comment",
      },
      { "<leader>ft", "<cmd>TodoQuickFix<cr>", desc = "Find todos" },
    },
  },
}
