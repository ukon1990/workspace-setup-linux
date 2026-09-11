local treesitter_langs = {
  "bash",
  "c",
  "css",
  "html",
  "java",
  "javascript",
  "json",
  "kotlin",
  "lua",
  "markdown",
  "markdown_inline",
  "query",
  "scss",
  "tsx",
  "typescript",
  "vim",
  "vimdoc",
  "yaml",
}

return {
  {
    -- Neovim 0.12 requires the rewritten `main` branch (master is incompatible
    -- and crashes on markdown injections / render-markdown).
    "nvim-treesitter/nvim-treesitter",
    branch = "main",
    lazy = false,
    build = ":TSUpdate",
    config = function()
      require("nvim-treesitter").setup({
        install_dir = vim.fn.stdpath("data") .. "/site",
      })

      -- Install missing parsers (async; no-op if already present)
      pcall(function()
        require("nvim-treesitter").install(treesitter_langs)
      end)

      -- Enable highlighting + indent for installed parsers
      vim.api.nvim_create_autocmd("FileType", {
        group = vim.api.nvim_create_augroup("treesitter_start", { clear = true }),
        callback = function(event)
          local ft = event.match
          local lang = vim.treesitter.language.get_lang(ft) or ft
          if not vim.tbl_contains(treesitter_langs, lang) and not vim.tbl_contains(treesitter_langs, ft) then
            -- Still try — filetype may map to an installed parser (e.g. typescriptreact → tsx)
            local ok = pcall(vim.treesitter.start, event.buf)
            if ok then
              vim.bo[event.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
            end
            return
          end
          local ok = pcall(vim.treesitter.start, event.buf)
          if ok then
            vim.bo[event.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
          end
        end,
      })
    end,
  },
  {
    "numToStr/Comment.nvim",
    event = { "BufReadPost", "BufNewFile" },
    opts = {},
  },
  {
    "echasnovski/mini.pairs",
    event = "InsertEnter",
    opts = {},
  },
  {
    "echasnovski/mini.surround",
    keys = {
      { "sa", mode = { "n", "v" }, desc = "Add surrounding" },
      { "sd", desc = "Delete surrounding" },
      { "sr", desc = "Replace surrounding" },
      { "sf", desc = "Find surrounding" },
      { "sF", desc = "Find surrounding (left)" },
      { "sh", desc = "Highlight surrounding" },
      { "sn", desc = "Update n_lines" },
    },
    opts = {
      mappings = {
        add = "sa",
        delete = "sd",
        find = "sf",
        find_left = "sF",
        highlight = "sh",
        replace = "sr",
        update_n_lines = "sn",
      },
    },
  },
}
