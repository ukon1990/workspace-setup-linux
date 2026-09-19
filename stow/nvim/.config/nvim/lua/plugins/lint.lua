return {
  {
    "mfussenegger/nvim-lint",
    event = { "BufReadPost", "BufNewFile", "BufWritePost", "InsertLeave" },
    config = function()
      local lint = require("lint")

      local function eslint_lsp_attached(bufnr)
        return #vim.lsp.get_clients({ bufnr = bufnr, name = "eslint" }) > 0
      end

      local function try_lint(bufnr, notify)
        bufnr = bufnr or vim.api.nvim_get_current_buf()
        local ft = vim.bo[bufnr].filetype
        local eslint_ft = ft == "javascript"
          or ft == "javascriptreact"
          or ft == "typescript"
          or ft == "typescriptreact"
          or ft == "html"
        if eslint_ft and eslint_lsp_attached(bufnr) then
          if notify then
            vim.notify("ESLint LSP is already providing diagnostics", vim.log.levels.INFO, { title = "lint" })
          end
          return
        end
        lint.try_lint(nil, { ignore_errors = not notify })
      end

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
        callback = function(event)
          -- Avoid noisy failures outside lint-configured projects
          try_lint(event.buf, false)
        end,
      })

      vim.keymap.set("n", "<leader>xl", function()
        try_lint(0, true)
      end, { desc = "Run linter" })
    end,
  },
}
