return {
  {
    "mfussenegger/nvim-lint",
    event = { "BufReadPost", "BufNewFile", "BufWritePost", "InsertLeave" },
    config = function()
      local lint = require("lint")

      lint.linters_by_ft = {
        javascript = { "eslint_d" },
        javascriptreact = { "eslint_d" },
        typescript = { "eslint_d" },
        typescriptreact = { "eslint_d" },
        -- Angular often uses .ts / .html; eslint_d picks up project config when present
        html = { "eslint_d" },
        kotlin = { "ktlint" },
      }

      local group = vim.api.nvim_create_augroup("nvim_lint", { clear = true })
      vim.api.nvim_create_autocmd({ "BufEnter", "BufWritePost", "InsertLeave" }, {
        group = group,
        callback = function()
          -- Avoid noisy failures outside lint-configured projects
          lint.try_lint(nil, { ignore_errors = true })
        end,
      })

      vim.keymap.set("n", "<leader>xl", function()
        lint.try_lint()
      end, { desc = "Run linter" })
    end,
  },
}
