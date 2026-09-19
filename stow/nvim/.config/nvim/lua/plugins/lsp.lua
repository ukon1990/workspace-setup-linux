return {
  {
    "mason-org/mason.nvim",
    cmd = { "Mason", "MasonInstall", "MasonUninstall", "MasonUpdate", "MasonLog" },
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
    opts = function()
      local ensure_installed = {
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
      }
      -- csharp_ls requires the .NET SDK to install/run; skip it when `dotnet`
      -- isn't on PATH so Mason doesn't repeatedly fail-install it every start.
      if vim.fn.executable("dotnet") == 1 then
        table.insert(ensure_installed, "csharp_ls")
      end
      return {
        ensure_installed = ensure_installed,
        -- jdtls is started via nvim-jdtls / ftplugin/java.lua
        automatic_enable = {
          exclude = { "jdtls" },
        },
      }
    end,
  },
  {
    "neovim/nvim-lspconfig",
    event = { "BufReadPre", "BufNewFile" },
    dependencies = {
      "mason-org/mason.nvim",
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
        root_dir = function(bufnr, on_dir)
          local fname = vim.api.nvim_buf_get_name(bufnr)
          -- angularls owns TypeScript in Angular/Nx workspaces. Running both
          -- servers duplicates diagnostics, completion and indexing work.
          if vim.fs.root(fname, { "angular.json", "nx.json" }) then
            return
          end
          local root = vim.fs.root(fname, { "tsconfig.json", "jsconfig.json", "package.json", ".git" })
          if root then
            on_dir(root)
          end
        end,
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
      -- Terminate any intellij-server processes already bound to this
      -- project's system-path. kotlin_lsp is detached (survives crashes /
      -- force-kills), so orphans can accumulate and hold the RocksDB index
      -- LOCK, making new servers fail with "Resource temporarily unavailable".
      -- If a live client already existed for this root in the *current*
      -- Neovim instance, lspconfig would reuse it instead of calling this
      -- cmd() again, so anything found here is guaranteed to be an orphan.
      local function stop_stale_kotlin_lsp(system)
        if vim.fn.executable("pgrep") ~= 1 then
          return
        end
        local escaped = system:gsub("([%.%^%$%*%+%?%(%)%[%]%{%}%|\\])", "\\%1")
        local pattern = "intellij-server.*--system-path=" .. escaped
        local pids = vim.fn.systemlist({ "pgrep", "-f", pattern })
        if vim.v.shell_error ~= 0 or #pids == 0 then
          return
        end
        for _, pid in ipairs(pids) do
          pid = tonumber(pid)
          if pid then
            pcall(vim.uv.kill, pid, "sigterm")
          end
        end
        vim.uv.sleep(300)
        local remaining = vim.fn.systemlist({ "pgrep", "-f", pattern })
        if vim.v.shell_error == 0 then
          for _, pid in ipairs(remaining) do
            pid = tonumber(pid)
            if pid then
              pcall(vim.uv.kill, pid, "sigkill")
            end
          end
        end
      end

      vim.lsp.config("kotlin_lsp", {
        -- Per-project system path avoids cross-talk; still only one server per project
        -- may hold the shared RocksDB index lock.
        cmd = function(dispatchers, config)
          local root = config.root_dir or vim.uv.cwd() or "."
          local hash = vim.fn.sha256(root):sub(1, 8)
          local name = vim.fn.fnamemodify(root, ":t")
          local system = vim.fn.stdpath("cache") .. "/kotlin-lsp-workspaces/" .. name .. "-" .. hash
          vim.fn.mkdir(system, "p")
          stop_stale_kotlin_lsp(system)
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

      -- Swift: system sourcekit-lsp (Xcode / CLT); skip when missing
      if vim.fn.executable("sourcekit-lsp") == 1 then
        vim.lsp.config("sourcekit", {
          cmd = { "sourcekit-lsp" },
          filetypes = { "swift" },
          root_markers = { "Package.swift", ".git" },
          root_dir = function(bufnr, on_dir)
            local fname = vim.api.nvim_buf_get_name(bufnr)
            local root = vim.fs.root(fname, { "Package.swift", ".git" })
            if not root then
              local xcode = vim.fs.find(function(name)
                return name:match("%.xcodeproj$") or name:match("%.xcworkspace$")
              end, { upward = true, path = vim.fs.dirname(fname), limit = 1 })[1]
              if xcode then
                root = vim.fs.dirname(xcode)
              end
            end
            if root then
              on_dir(root)
            end
          end,
        })
        vim.lsp.enable("sourcekit")
      end

      vim.lsp.config("csharp_ls", {
        root_markers = { "*.sln", "*.csproj", ".git" },
        root_dir = function(bufnr, on_dir)
          local fname = vim.api.nvim_buf_get_name(bufnr)
          local root = vim.fs.root(fname, function(name)
            return name:match("%.sln$") or name:match("%.csproj$") or name == ".git"
          end)
          if root then
            on_dir(root)
          end
        end,
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
    event = "VeryLazy",
    dependencies = { "mason-org/mason.nvim" },
    opts = {
      integrations = {
        ["mason-lspconfig"] = false,
        ["mason-null-ls"] = false,
        ["mason-nvim-dap"] = false,
      },
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
