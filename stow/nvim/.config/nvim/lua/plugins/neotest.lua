-- Multi-language test runner (IntelliJ-like summary / gutter / output).
-- Java/Kotlin: neotest-maven (mvnw) for Maven, neotest-gradle for Gradle.
-- Mixed monorepos seed every Maven/Gradle/npm root before running suites.

local discovery = require("config.neotest_discovery")

--- Maven adapter for Java + Kotlin Surefire/Failsafe tests.
local function maven_adapter()
  return require("config.neotest_maven").create()
end

--- Gradle adapter for Kotlin + Java (kotlin.test / JUnit via `./gradlew test`).
local function gradle_adapter()
  local adapter = require("neotest-gradle")
  local patterns = {
    "Test%.kt$",
    "Tests%.kt$",
    "IT%.kt$",
    "Spec%.kt$",
    "Test%.java$",
    "Tests%.java$",
    "IT%.java$",
    "Spec%.java$",
  }
  adapter.is_test_file = function(file_path)
    if discovery.nearest_jvm_build(file_path) ~= "gradle" then
      return false
    end
    for _, pattern in ipairs(patterns) do
      if file_path:match(pattern) then
        return true
      end
    end
    return false
  end
  adapter.filter_dir = function(name)
    return name ~= "build"
      and name ~= ".gradle"
      and name ~= "node_modules"
      and name ~= "target"
      and name ~= ".git"
  end
  return require("config.neotest_gradle").patch(adapter)
end

--- Prefer Vitest when present so Jest and Vitest never claim the same package.
local function js_package_cwd(path)
  local tools = require("config.project_tools")
  local dir = path and (vim.fn.isdirectory(path) == 1 and path or vim.fs.dirname(path)) or vim.uv.cwd()
  local vitest = discovery.nearest_vitest_package(dir)
  if vitest then
    return vitest
  end
  return tools.nearest_npm_dir(dir) or dir
end

local function gate_js_adapter(adapter, kind)
  adapter.root = function(dir)
    if kind == "vitest" then
      return discovery.nearest_vitest_package(dir)
    end
    local tools = require("config.project_tools")
    local pkg = tools.nearest_npm_dir(dir)
    if not pkg then
      return nil
    end
    -- Nested packages under a Vitest root (e.g. ethereal-ui) belong to Vitest.
    local vitest_root = discovery.nearest_vitest_package(dir)
    if vitest_root then
      return nil
    end
    if discovery.npm_has_jest(pkg) or discovery.npm_has_react_scripts(pkg) then
      return pkg
    end
    return nil
  end
  adapter.is_test_file = function(path)
    if not discovery.is_js_test_file(path) then
      return false
    end
    local vitest_root = discovery.nearest_vitest_package(path)
    if kind == "vitest" then
      return vitest_root ~= nil
    end
    if vitest_root then
      return false
    end
    local pkg = require("config.project_tools").nearest_npm_dir(vim.fs.dirname(path))
    return pkg ~= nil and (discovery.npm_has_jest(pkg) or discovery.npm_has_react_scripts(pkg))
  end
  return adapter
end

--- Only activate Rust when a Cargo project exists; never warn otherwise.
local function rust_adapter()
  local adapter = require("neotest-rust")({
    args = { "--no-capture" },
    dap_adapter = "codelldb",
  })
  local orig_root = adapter.root
  adapter.root = function(dir)
    if not discovery.has_cargo(dir) then
      return nil
    end
    return orig_root(dir)
  end
  return adapter
end

--- Side summary (tree + pass/fail) + shared bottom tool panel (logs).
local function open_test_ui()
  local neotest = require("neotest")
  local tool_panel = require("config.tool_panel")
  tool_panel.show_tests({ focus = false })
  -- Prefer Overseer runner tabs; keep the shared panel as a fallback tab.
  neotest.output_panel.open()
  vim.schedule(function()
    local buf = neotest.output_panel.buffer()
    if buf then
      tool_panel.show_buf(buf, { focus = false })
    end
  end)

  local client = neotest.workspace and neotest.workspace.client
  if client then
    discovery.ensure_discovered(client, {
      on_ready = function()
        pcall(function()
          require("neotest").summary.render()
        end)
      end,
    })
  end
end

local function run_with_ui(run_fn)
  return function()
    open_test_ui()
    vim.schedule(run_fn)
  end
end

local function adapter_has_path(neotest, adapter_id, path)
  local tree = neotest.state.positions(adapter_id)
  if not tree then
    return false
  end
  local prefix = vim.fs.normalize(path)
  prefix = prefix:sub(-1) == "/" and prefix or (prefix .. "/")
  for _, position in tree:iter() do
    if position.path then
      local position_path = vim.fs.normalize(position.path)
      if position_path == path or position_path:sub(1, #prefix) == prefix then
        return true
      end
    end
  end
  return false
end

local function run_discovered_suites(adapter_ids, path)
  local neotest = require("neotest")
  local to_run = {}
  for _, adapter_id in ipairs(discovery.runnable_adapter_ids(adapter_ids)) do
    if not path or adapter_has_path(neotest, adapter_id, path) then
      to_run[#to_run + 1] = adapter_id
    end
  end
  if #to_run == 0 then
    vim.notify(
      path and ("No test suites under " .. path) or "No test suites discovered",
      vim.log.levels.INFO,
      { title = "neotest" }
    )
    return
  end

  -- Schedule each suite from the main loop so nio.create does not await the
  -- previous suite (which would serialize Maven before Vitest, and abort the
  -- rest if the output-panel terminal listener throws).
  for _, adapter_id in ipairs(to_run) do
    vim.schedule(function()
      if path then
        neotest.run.run({ path, adapter = adapter_id })
      else
        neotest.run.run({ suite = true, adapter = adapter_id })
      end
    end)
  end
end

local function run_after_discovery(path)
  local neotest = require("neotest")
  local client = neotest.workspace and neotest.workspace.client
  if not client then
    neotest.summary.open({ enter = false })
    discovery.set_loading("Discovering tests…")
    local started = vim.uv.now()
    local previous
    local stable_since
    local function poll()
      local adapter_ids = neotest.state.adapter_ids()
      local signature = discovery.positions_signature(adapter_ids)
      if signature ~= previous then
        previous = signature
        stable_since = vim.uv.now()
        discovery.set_loading(("Discovering tests… %d suite(s)"):format(#adapter_ids))
      end
      if #adapter_ids > 0 and stable_since and vim.uv.now() - stable_since >= 600 then
        discovery.set_loading(nil)
        run_discovered_suites(adapter_ids, path)
      elseif vim.uv.now() - started < 45000 then
        vim.defer_fn(poll, 150)
      else
        discovery.set_loading(nil)
        if #adapter_ids > 0 then
          run_discovered_suites(adapter_ids, path)
        else
          vim.notify("No test suites discovered", vim.log.levels.INFO, { title = "neotest" })
        end
      end
    end
    vim.defer_fn(poll, 100)
    return
  end

  discovery.wait_then_run(client, {
    path = path,
    on_ready = function(adapter_ids)
      run_discovered_suites(adapter_ids, path)
    end,
  })
end

local function run_suite()
  run_after_discovery()
end

local function explorer_directory()
  local ok, pickers = pcall(function()
    return Snacks.picker.get({ source = "explorer", tab = false })
  end)
  if not ok then
    return nil
  end
  for _, picker in ipairs(pickers) do
    if picker:is_focused() then
      local item = picker:current()
      if item and item.file then
        return item.dir and item.file or vim.fs.dirname(item.file)
      end
    end
  end
end

local function run_directory()
  local path = explorer_directory()
  if not path then
    local current = vim.fn.expand("%:p")
    path = vim.fn.isdirectory(current) == 1 and current or vim.fs.dirname(current)
  end
  if not path or path == "" then
    vim.notify("No directory selected", vim.log.levels.INFO, { title = "neotest" })
    return
  end
  run_after_discovery(vim.fs.normalize(path))
end

local function run_failed()
  local neotest = require("neotest")
  if neotest.failed and neotest.failed.run then
    neotest.failed.run()
    return
  end
  vim.notify("Failed-test tracker not ready yet", vim.log.levels.WARN, { title = "neotest" })
end

local function jump_to_code()
  if vim.bo.filetype == "neotest-summary" then
    vim.api.nvim_feedkeys("i", "m", false)
    return
  end

  local neotest = require("neotest")
  local path = vim.fn.expand("%:p")
  local row = vim.api.nvim_win_get_cursor(0)[1] - 1
  local best, best_dist

  for _, adapter_id in ipairs(neotest.state.adapter_ids()) do
    local tree = neotest.state.positions(adapter_id)
    if tree then
      local file_node = tree:get_key(path)
      if file_node then
        for _, node in file_node:iter_nodes() do
          local pos = node:data()
          if pos.type == "test" or pos.type == "namespace" then
            local range = node:closest_value_for("range")
            if range then
              local dist = math.abs(range[1] - row)
              if not best_dist or dist < best_dist then
                best_dist = dist
                best = range
              end
            end
          end
        end
      end
    end
  end

  if best then
    vim.api.nvim_win_set_cursor(0, { best[1] + 1, best[2] })
  else
    vim.notify("No test position found in this file", vim.log.levels.INFO, { title = "neotest" })
  end
end

--- Right-click menu on the summary tree.
local function summary_context_menu()
  local mp = vim.fn.getmousepos()
  if mp.winid ~= 0 and vim.api.nvim_win_is_valid(mp.winid) then
    vim.api.nvim_set_current_win(mp.winid)
    pcall(vim.api.nvim_win_set_cursor, mp.winid, { mp.line, math.max(0, mp.column - 1) })
  end

  local choices = {
    { label = "Jump to code", key = "i" },
    { label = "Show output", key = "o" },
    { label = "Run", key = "r" },
    { label = "Mark / unmark", key = "m" },
    { label = "Expand / collapse", key = "\r" },
  }

  vim.ui.select(choices, {
    prompt = "Test action",
    format_item = function(item)
      return item.label
    end,
  }, function(choice)
    if not choice then
      return
    end
    vim.api.nvim_feedkeys(choice.key, "m", false)
  end)
end

local function setup_summary_mouse()
  vim.api.nvim_create_autocmd("User", {
    pattern = "NeotestSummaryOpen",
    callback = function()
      for _, buf in ipairs(vim.api.nvim_list_bufs()) do
        if vim.bo[buf].filetype == "neotest-summary" then
          vim.keymap.set("n", "<RightMouse>", summary_context_menu, {
            buffer = buf,
            silent = true,
            desc = "Test context menu",
          })
        end
      end
    end,
  })

  vim.api.nvim_create_autocmd("FileType", {
    pattern = "neotest-summary",
    callback = function(event)
      vim.keymap.set("n", "<RightMouse>", summary_context_menu, {
        buffer = event.buf,
        silent = true,
        desc = "Test context menu",
      })
    end,
  })
end

return {
  {
    "nvim-neotest/neotest",
    dependencies = {
      "nvim-neotest/nvim-nio",
      "nvim-lua/plenary.nvim",
      "nvim-treesitter/nvim-treesitter",
      "mfussenegger/nvim-dap",
      "stevearc/overseer.nvim",
      "weilbith/neotest-gradle",
      "nvim-neotest/neotest-jest",
      "marilari88/neotest-vitest",
      "nvim-neotest/neotest-python",
      "fredrikaverpil/neotest-golang",
      "rouge8/neotest-rust",
    },
    keys = {
      {
        "<leader>Tr",
        run_with_ui(function()
          require("neotest").run.run()
        end),
        desc = "Run nearest test",
      },
      {
        "<leader>Tf",
        run_with_ui(function()
          require("neotest").run.run(vim.fn.expand("%"))
        end),
        desc = "Run current file",
      },
      {
        "<leader>Td",
        run_with_ui(run_directory),
        desc = "Run tests in selected directory",
      },
      {
        "<leader>Ta",
        run_with_ui(run_suite),
        desc = "Run all tests",
      },
      {
        "<leader>Tl",
        run_with_ui(function()
          require("neotest").run.run_last()
        end),
        desc = "Run last",
      },
      {
        "<leader>TF",
        run_with_ui(run_failed),
        desc = "Re-run failed tests",
      },
      {
        "<leader>Tm",
        run_with_ui(function()
          require("neotest").summary.run_marked()
        end),
        desc = "Run marked tests",
      },
      {
        "<leader>Tj",
        jump_to_code,
        desc = "Jump to test code",
      },
      {
        "<leader>Ts",
        function()
          require("config.tool_panel").toggle_tests()
        end,
        desc = "Toggle summary",
      },
      {
        "<leader>To",
        function()
          require("neotest").output.open({ enter = true, auto_close = true })
        end,
        desc = "Show test output",
      },
      {
        "<leader>Tp",
        function()
          require("neotest").output_panel.toggle()
        end,
        desc = "Toggle output panel",
      },
      {
        "<leader>Tu",
        function()
          open_test_ui()
        end,
        desc = "Open test UI (summary + panel)",
      },
      {
        "<leader>Tw",
        run_with_ui(function()
          require("neotest").watch.toggle(vim.fn.expand("%"))
        end),
        desc = "Toggle watch file",
      },
      {
        "<leader>Tx",
        function()
          require("neotest").run.stop()
        end,
        desc = "Stop test",
      },
      {
        "<leader>TD",
        run_with_ui(function()
          require("neotest").run.run({ strategy = "dap" })
        end),
        desc = "Debug nearest test",
      },
      {
        "[T",
        function()
          require("neotest").jump.prev({ status = "failed" })
        end,
        desc = "Previous failed test",
      },
      {
        "]T",
        function()
          require("neotest").jump.next({ status = "failed" })
        end,
        desc = "Next failed test",
      },
    },
    config = function()
      setup_summary_mouse()

      local neotest_lib = require("neotest.lib")
      local neotest_config = require("neotest.config")

      -- Label stacked adapters with their project folder (backend / frontend).
      -- summary.lua returns a factory; the Summary class is a closed-over upvalue.
      local summary_factory = require("neotest.consumers.summary.summary")
      local Summary
      for i = 1, 8 do
        local name, value = debug.getupvalue(summary_factory, i)
        if name == "Summary" then
          Summary = value
          break
        end
      end
      if Summary and Summary._write_header then
        local orig_write_header = Summary._write_header
        function Summary:_write_header(canvas, adapter_id, tree)
          local label = discovery.adapter_header_label(adapter_id)
          local orig_write = canvas.write
          local replaced = false
          canvas.write = function(self, text, opts)
            if
              not replaced
              and opts
              and opts.group == neotest_config.highlights.adapter_name
            then
              replaced = true
              return orig_write(self, label, opts)
            end
            return orig_write(self, text, opts)
          end
          orig_write_header(self, canvas, adapter_id, tree)
          canvas.write = orig_write
        end
      end

      -- Neotest's default chooser can mistake another normal-looking tool
      -- window for the editor. Always send summary jumps to an editor window.
      neotest_lib.ui.open_buf = function(bufnr, line, column)
        require("config.tool_panel").open_in_editor(bufnr, line, column)
      end

      -- Reusing the shared output dock means the panel buffer may already be a
      -- terminal when a second adapter streams results. Reuse the existing
      -- channel instead of calling nvim_open_term again (which aborts the suite).
      local orig_open_term = neotest_lib.ui.open_term
      neotest_lib.ui.open_term = function(buf, opts)
        if type(buf) == "number" and vim.api.nvim_buf_is_valid(buf) then
          for _, info in ipairs(vim.api.nvim_list_chans()) do
            if info.buffer == buf and info.mode == "terminal" then
              return info.id
            end
          end
        end
        local ok, chan_or_err = pcall(orig_open_term, buf, opts)
        if ok then
          return chan_or_err
        end
        if type(buf) == "number" and vim.api.nvim_buf_is_valid(buf) then
          for _, info in ipairs(vim.api.nvim_list_chans()) do
            if info.buffer == buf and info.mode == "terminal" then
              return info.id
            end
          end
        end
        error(chan_or_err)
      end

      require("neotest").setup({
        icons = require("config.neotest_icons"),
        default_strategy = "overseer",
        strategies = {
          overseer = {
            components = { "default_neotest" },
          },
        },
        overseer = {
          enabled = true,
          force_default = true,
        },
        adapters = {
          maven_adapter(),
          gradle_adapter(),
          gate_js_adapter(
            require("neotest-jest")({
              jestCommand = "npm test --",
              cwd = js_package_cwd,
            }),
            "jest"
          ),
          gate_js_adapter(
            require("neotest-vitest")({
              cwd = js_package_cwd,
              filter_dir = function(name)
                return name ~= "node_modules"
                  and name ~= "dist"
                  and name ~= "coverage"
                  and name ~= "storybook-static"
              end,
            }),
            "vitest"
          ),
          require("neotest-python")({
            dap = { justMyCode = false },
            runner = "pytest",
          }),
          require("neotest-golang")({}),
          rust_adapter(),
        },
        consumers = {
          overseer = require("neotest.consumers.overseer"),
          --- Seed nested Maven/npm roots and wait until expected suites appear.
          workspace = function(client)
            client.listeners.started = function()
              discovery.ensure_discovered(client, {
                on_ready = function()
                  pcall(function()
                    require("neotest").summary.render()
                  end)
                end,
              })
            end
            return {
              client = client,
              refresh = function(anchor)
                return discovery.refresh_adapters(client, anchor)
              end,
            }
          end,
          --- Track failed tests for <leader>TF
          failed = function(client)
            ---@type table<string, table<string, boolean>>
            local failed = {}

            client.listeners.results = function(adapter_id, results, partial)
              if partial then
                return
              end
              failed[adapter_id] = failed[adapter_id] or {}
              for pos_id, result in pairs(results) do
                if result.status == "failed" then
                  failed[adapter_id][pos_id] = true
                else
                  failed[adapter_id][pos_id] = nil
                end
              end
            end

            return {
              run = function()
                local any = false
                for adapter_id, positions in pairs(failed) do
                  for pos_id, is_failed in pairs(positions) do
                    if is_failed then
                      any = true
                      require("neotest").run.run({ pos_id, adapter = adapter_id })
                    end
                  end
                end
                if not any then
                  vim.notify("No failed tests to re-run", vim.log.levels.INFO, { title = "neotest" })
                end
              end,
            }
          end,
        },
        status = {
          enabled = true,
          signs = true,
          virtual_text = true,
        },
        diagnostic = {
          enabled = true,
          severity = vim.diagnostic.severity.ERROR,
        },
        floating = {
          border = "rounded",
          max_height = 0.8,
          max_width = 0.9,
        },
        output = {
          enabled = true,
          open_on_run = false,
        },
        output_panel = {
          enabled = true,
          -- Reuse shared bottom tool panel (with overseer), not a new botright split
          open = function()
            return require("config.tool_panel").ensure_win({ focus = false })
          end,
        },
        summary = {
          enabled = true,
          animated = true,
          expand_errors = true,
          follow = true,
          open = function()
            return require("config.tool_panel").ensure_sidebar("tests", { focus = false })
          end,
          mappings = {
            attach = "a",
            expand = { "<CR>", "<2-LeftMouse>" },
            expand_all = "e",
            jumpto = { "i", "g" },
            output = "o",
            run = { "r", "<C-LeftMouse>" },
            mark = "m",
            run_marked = "R",
            clear_marked = "M",
            next_failed = "J",
            prev_failed = "K",
            short = "O",
            stop = "u",
            watch = "w",
            help = "?",
          },
        },
        quickfix = {
          enabled = true,
          open = false,
        },
      })
    end,
  },
}
