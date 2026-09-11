return {
  {
    "MeanderingProgrammer/render-markdown.nvim",
    ft = { "markdown", "mdx" },
    dependencies = {
      "nvim-treesitter/nvim-treesitter",
      "nvim-tree/nvim-web-devicons",
    },
    opts = {
      file_types = { "markdown", "mdx" },
      debounce = 100,
      heading = {
        enabled = true,
        sign = false,
      },
      code = {
        enabled = true,
        sign = false,
        width = "block",
        border = "thin",
      },
      bullet = { enabled = true },
    },
    keys = {
      {
        "<leader>um",
        function()
          require("render-markdown").toggle()
        end,
        desc = "Toggle markdown render",
      },
    },
  },
}
