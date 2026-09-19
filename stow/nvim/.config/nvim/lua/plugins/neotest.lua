-- Multi-language test runner (IntelliJ-like summary / gutter / output).
-- Rust adapter needs cargo-nextest on PATH: `cargo install cargo-nextest`
-- Kotlin/JUnit on Gradle: neotest-gradle (neotest-java is Java/.java only).

local GRADLE_MARKERS = {
  "gradlew",
  "settings.gradle",
  "settings.gradle.kts",
  "build.gradle",
  "build.gradle.kts",
}

local function has_gradle(path)
  local dir = path and (vim.fn.isdirectory(path) == 1 and path or vim.fs.dirname(path)) or vim.uv.cwd()
  return vim.fs.find(GRADLE_MARKERS, { upward = true, path = dir, limit = 1 })[1] ~= nil
end

--- Restrict neotest-java to *.java — it otherwise matches *Test.kt by classname
--- and crashes treesitter (Java query on Kotlin grammar).
local function java_adapter()
  local adapter = require("neotest-java")({
    ignore_wrapper = false,
  })
  local orig_root = adapter.root
  local orig_is_test = adapter.is_test_file
  adapter.root = function(dir)
    if has_gradle(dir) then
      return nil
    end
    return orig_root(dir)
  end
  adapter.is_test_file = function(path)
    if not path:match("%.java$") then
      return false
    end
    if has_gradle(path) then
      return false
    end
    return orig_is_test(path)
  end
  return adapter
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

--- Prevent jest/vitest from claiming Gradle/KMP repos that also have package.json.
local function gate_js_adapter(adapter)
  local orig_root = adapter.root
  adapter.root = function(dir)
    if has_gradle(dir) then
      return nil
    end
    return orig_root(dir)
  end
  return adapter
end

--- Side summary (tree + pass/fail) + bottom output panel (logs).
local function open_test_ui()
  local neotest = require("neotest")
  neotest.summary.open()
  neotest.output_panel.open()
end

local function run_with_ui(run_fn)
  return function()
    open_test_ui()
    vim.schedule(run_fn)
  end
end

--- Pick a single adapter for suite run (never fire all adapters on one root).
local function suite_adapter_id()
  local neotest = require("neotest")
  local path = vim.fn.expand("%:p")
  local ids = neotest.state.adapter_ids()

  if path ~= "" and #ids > 0 then
    for _, adapter_id in ipairs(ids) do
      local tree = neotest.state.positions(adapter_id)
      if tree and tree:get_key(path) then
        return adapter_id
      end
    end
  end

  for _, adapter_id in ipairs(ids) do
    if adapter_id:find("gradle", 1, true) then
      return adapter_id
    end
  end

  return ids[1]
end

local function run_suite()
  local neotest = require("neotest")
  local adapter_id = suite_adapter_id()
  if adapter_id then
    neotest.run.run({ suite = true, adapter = adapter_id })
    return
  end

  -- Cold start: wait briefly for discovery after opening the summary
  vim.defer_fn(function()
    local id = suite_adapter_id()
    if id then
      neotest.run.run({ suite = true, adapter = id })
    else
      neotest.run.run(vim.uv.cwd())
    end
  end, 200)
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
      "weilbith/neotest-gradle",
      "rcasia/neotest-java",
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
        run_with_ui(function()
          require("neotest").run.run(vim.fn.expand("%:p:h"))
        end),
        desc = "Run tests in directory",
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
          require("neotest").summary.toggle()
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
      if vim.fn.executable("cargo-nextest") ~= 1 and vim.fn.executable("nextest") ~= 1 then
        vim.notify_once(
          "neotest-rust needs cargo-nextest (`cargo install cargo-nextest`)",
          vim.log.levels.WARN,
          { title = "neotest" }
        )
      end

      setup_summary_mouse()

      require("neotest").setup({
        adapters = {
          gradle_adapter(),
          java_adapter(),
          gate_js_adapter(require("neotest-jest")({
            jestCommand = "npm test --",
            cwd = function()
              return vim.fn.getcwd()
            end,
          })),
          gate_js_adapter(require("neotest-vitest")({
            filter_dir = function(name)
              return name ~= "node_modules"
            end,
          })),
          require("neotest-python")({
            dap = { justMyCode = false },
            runner = "pytest",
          }),
          require("neotest-golang")({}),
          require("neotest-rust")({
            args = { "--no-capture" },
            dap_adapter = "codelldb",
          }),
        },
        consumers = {
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
          open_on_run = "short",
        },
        output_panel = {
          enabled = true,
          open = "botright split | resize 12",
        },
        summary = {
          enabled = true,
          animated = true,
          expand_errors = true,
          follow = true,
          open = "botright vsplit | vertical resize 45",
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
