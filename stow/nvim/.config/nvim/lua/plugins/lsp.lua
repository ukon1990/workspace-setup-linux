return {
  {
    "mason-org/mason.nvim",
    lazy = false,
    build = ":MasonUpdate",
    opts = {
      ui = {
        border = "rounded",
        icons = {
          package_installed = "✓",
          package_pending = "➜",
          package_uninstalled = "✗",
        },
      },
    },
  },
  {
    "mason-org/mason-lspconfig.nvim",
    event = { "BufReadPre", "BufNewFile" },
    dependencies = {
      "mason-org/mason.nvim",
      "neovim/nvim-lspconfig",
    },
    opts = {
      ensure_installed = {
        "lua_ls",
        "ts_ls",
        "angularls",
        "eslint",
        "html",
        "cssls",
        "jsonls",
        "tailwindcss",
        "emmet_language_server",
        "marksman",
        "kotlin_lsp",
        "jdtls",
      },
      -- jdtls is started via nvim-jdtls / ftplugin/java.lua
      automatic_enable = {
        exclude = { "jdtls" },
      },
    },
  },
  {
    "neovim/nvim-lspconfig",
    event = { "BufReadPre", "BufNewFile" },
    dependencies = {
      "mason-org/mason.nvim",
      "mason-org/mason-lspconfig.nvim",
    },
    config = function()
      vim.diagnostic.config({
        virtual_text = { spacing = 2, source = "if_many" },
        severity_sort = true,
        float = { border = "rounded", source = true },
        signs = {
          text = {
            [vim.diagnostic.severity.ERROR] = "E",
            [vim.diagnostic.severity.WARN] = "W",
            [vim.diagnostic.severity.INFO] = "I",
            [vim.diagnostic.severity.HINT] = "H",
          },
        },
      })

      -- Server tweaks merged with nvim-lspconfig defaults (Nvim 0.11+)
      vim.lsp.config("lua_ls", {
        settings = {
          Lua = {
            runtime = { version = "LuaJIT" },
            diagnostics = { globals = { "vim", "Snacks" } },
            workspace = {
              checkThirdParty = false,
              library = {
                vim.env.VIMRUNTIME,
              },
            },
            telemetry = { enable = false },
          },
        },
      })

      vim.lsp.config("ts_ls", {
        root_markers = { "tsconfig.json", "jsconfig.json", "package.json", ".git" },
      })

      -- Only activate inside Angular/Nx workspaces (never fall back to .git alone)
      vim.lsp.config("angularls", {
        root_markers = { "angular.json", "nx.json" },
        root_dir = function(bufnr, on_dir)
          local fname = vim.api.nvim_buf_get_name(bufnr)
          local root = vim.fs.root(fname, { "angular.json", "nx.json" })
          if root then
            on_dir(root)
          end
        end,
      })

      vim.lsp.config("cssls", {
        settings = {
          css = { validate = true },
          scss = { validate = true },
          less = { validate = true },
        },
      })

      -- Kotlin: JetBrains kotlin-lsp; prefer Gradle/Maven root; fall back to file dir
      vim.lsp.config("kotlin_lsp", {
        -- Per-project system path avoids cross-talk; still only one server per project
        -- may hold the shared RocksDB index lock.
        cmd = function(dispatchers, config)
          local root = config.root_dir or vim.uv.cwd() or "."
          local hash = vim.fn.sha256(root):sub(1, 8)
          local name = vim.fn.fnamemodify(root, ":t")
          local system = vim.fn.stdpath("cache") .. "/kotlin-lsp-workspaces/" .. name .. "-" .. hash
          vim.fn.mkdir(system, "p")
          return vim.lsp.rpc.start({
            "intellij-server",
            "--stdio",
            "--system-path=" .. system,
          }, dispatchers, {
            cwd = config.cmd_cwd,
            env = config.cmd_env,
            detached = config.detached,
          })
        end,
        root_dir = function(bufnr, on_dir)
          local fname = vim.api.nvim_buf_get_name(bufnr)
          local root = vim.fs.root(fname, {
            "settings.gradle",
            "settings.gradle.kts",
            "build.gradle",
            "build.gradle.kts",
            "pom.xml",
            ".git",
          })
          on_dir(root or vim.fs.dirname(fname))
        end,
        init_options = {
          -- JDK for symbol resolution (tracks SDKMAN `current`)
          defaultSdk = vim.fn.resolve(vim.fn.expand("~/.sdkman/candidates/java/current")),
        },
      })

      vim.lsp.config("jsonls", {
        settings = {
          json = {
            validate = { enable = true },
          },
        },
      })

      vim.lsp.config("emmet_language_server", {
        filetypes = {
          "html",
          "css",
          "scss",
          "sass",
          "less",
          "javascriptreact",
          "typescriptreact",
          "vue",
          "svelte",
        },
      })

      vim.api.nvim_create_autocmd("LspAttach", {
        group = vim.api.nvim_create_augroup("user_lsp_attach", { clear = true }),
        callback = function(event)
          local buf = event.buf
          local function map(mode, lhs, rhs, desc)
            vim.keymap.set(mode, lhs, rhs, { buffer = buf, desc = desc })
          end

          map("n", "gd", vim.lsp.buf.definition, "Goto definition")
          map("n", "gD", vim.lsp.buf.declaration, "Goto declaration")
          map("n", "gr", vim.lsp.buf.references, "References")
          map("n", "gi", vim.lsp.buf.implementation, "Goto implementation")
          map("n", "gt", vim.lsp.buf.type_definition, "Goto type definition")
          map("n", "K", vim.lsp.buf.hover, "Hover")
          map("n", "gK", vim.lsp.buf.signature_help, "Signature help")
          map("i", "<C-k>", vim.lsp.buf.signature_help, "Signature help")
          map("n", "<leader>ca", vim.lsp.buf.code_action, "Code action")
          map("n", "<leader>rn", vim.lsp.buf.rename, "Rename")
          map("n", "<leader>cl", vim.lsp.codelens.run, "Code lens")

          local client = vim.lsp.get_client_by_id(event.data.client_id)
          if client and client:supports_method("textDocument/inlayHint") then
            map("n", "<leader>uh", function()
              vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled({ bufnr = buf }), { bufnr = buf })
            end, "Toggle inlay hints")
          end
        end,
      })
    end,
  },
  {
    "WhoIsSethDaniel/mason-tool-installer.nvim",
    dependencies = { "mason-org/mason.nvim" },
    opts = {
      ensure_installed = {
        "prettier",
        "eslint_d",
        "ktlint",
        "google-java-format",
        "stylua",
        -- Java DAP / test (jdtls bundles in ftplugin/java.lua)
        "java-debug-adapter",
        "java-test",
      },
      automatic_installation = true,
    },
  },
}
