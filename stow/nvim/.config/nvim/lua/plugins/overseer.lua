return {
  {
    "stevearc/overseer.nvim",
    cmd = {
      "OverseerBuild",
      "OverseerClearCache",
      "OverseerInfo",
      "OverseerOpen",
      "OverseerRun",
      "OverseerTaskAction",
      "OverseerToggle",
    },
    opts = {
      strategy = "terminal",
      templates = { "builtin", "user" },
      disable_template_modules = {
        "overseer.template.npm",
      },
      -- Always open an interactive terminal for task output (shared bottom panel).
      component_aliases = {
        default = {
          "on_exit_set_status",
          "user.task_result",
          { "on_complete_dispose", require_view = { "SUCCESS", "FAILURE" } },
          "user.tool_panel",
        },
        -- Per-runner Neotest tasks: named tabs in the dock, no notify spam.
        default_neotest = {
          "on_exit_set_status",
          "user.neotest_tab",
          { "on_complete_dispose", require_view = { "SUCCESS", "FAILURE" } },
        },
      },
      task_list = {
        direction = "right",
        min_width = 36,
        max_width = 0.3,
        default_detail = 1,
        render = function(task)
          return require("overseer.render").format_standard(task)
        end,
      },
      form = {
        win_opts = {
          winblend = 0,
        },
      },
    },
    config = function(_, opts)
      require("overseer").setup(opts)
    end,
    keys = {
      {
        "<leader>rr",
        "<cmd>OverseerRun<cr>",
        desc = "Run task",
      },
      {
        "<leader>rt",
        function()
          require("config.tool_panel").toggle_tasks()
        end,
        desc = "Task list",
      },
      {
        "<leader>ra",
        "<cmd>OverseerTaskAction<cr>",
        desc = "Task action",
      },
      {
        "<leader>rl",
        function()
          local overseer = require("overseer")
          local tasks = overseer.list_tasks({ recent_first = true })
          if tasks[1] then
            overseer.run_action(tasks[1], "restart")
          else
            vim.notify("No recent tasks", vim.log.levels.WARN, { title = "overseer" })
          end
        end,
        desc = "Restart last task",
      },
      {
        "<leader>rc",
        function()
          require("overseer.commands").clear_cache()
          require("config.project_tools").clear_cache()
          vim.notify("Task discovery cache cleared", vim.log.levels.INFO, { title = "overseer" })
        end,
        desc = "Clear task cache",
      },
      {
        "<leader>ro",
        function()
          local overseer = require("overseer")
          local tasks = overseer.list_tasks({ recent_first = true })
          if not tasks[1] then
            vim.notify("No recent tasks", vim.log.levels.WARN, { title = "overseer" })
            return
          end
          local bufnr = tasks[1]:get_bufnr()
          if bufnr then
            require("config.tool_panel").show_buf(bufnr, { focus = true })
          else
            overseer.run_action(tasks[1], "open output")
          end
        end,
        desc = "Open task output",
      },
      {
        "<leader>r]",
        function()
          require("config.tool_panel").cycle(1)
        end,
        desc = "Next tool panel tab",
      },
      {
        "<leader>r[",
        function()
          require("config.tool_panel").cycle(-1)
        end,
        desc = "Prev tool panel tab",
      },
      {
        "<leader>rv",
        function()
          require("config.tool_panel").split_vertical()
        end,
        desc = "Tool panel side-by-side",
      },
      {
        "<leader>rb",
        function()
          require("overseer").run_task({ tags = { require("overseer").TAG.BUILD } })
        end,
        desc = "Run BUILD task",
      },
      {
        "<leader>rR",
        function()
          require("overseer").run_task({ tags = { require("overseer").TAG.RUN } })
        end,
        desc = "Run RUN task (dev/start/…)",
      },
      {
        "<leader>rT",
        function()
          require("overseer").run_task({ tags = { require("overseer").TAG.TEST } })
        end,
        desc = "Run TEST task (npm test/…)",
      },
      -- Mobile
      {
        "<leader>md",
        function()
          require("config.project_tools").pick_android_device(function(serial)
            if serial then
              vim.notify("Android device: " .. serial, vim.log.levels.INFO, { title = "mobile" })
            end
          end)
        end,
        desc = "Pick Android device",
      },
      {
        "<leader>mi",
        function()
          local tools = require("config.project_tools")
          local overseer = require("overseer")
          local ws = tools.discover_workspaces(vim.fn.expand("%:p:h"))
          local g
          for _, candidate in ipairs(ws.gradle) do
            if candidate.android then
              g = candidate
              break
            end
          end
          if not g then
            vim.notify("No Android Gradle project nearby", vim.log.levels.WARN, { title = "mobile" })
            return
          end
          local function start(serial)
            local task = g.current_module
                and (":" .. g.current_module:gsub("/", ":") .. ":installDebug")
              or "installDebug"
            local cmd = tools.gradle_cmd(g.root)
            table.insert(cmd, task)
            local env = {}
            if serial then
              vim.g.android_serial = serial
              env.ANDROID_SERIAL = serial
            end
            overseer
              .new_task({
                cmd = cmd,
                cwd = g.root,
                env = env,
                name = "gradle " .. task,
                components = require("config.task_errors").components("gradle"),
              })
              :start()
          end
          if vim.g.android_serial then
            start(vim.g.android_serial)
          else
            tools.pick_android_device(start)
          end
        end,
        desc = "Install debug (Android)",
      },
      {
        "<leader>ml",
        function()
          local cmd = { "adb" }
          if vim.g.android_serial then
            vim.list_extend(cmd, { "-s", vim.g.android_serial })
          end
          table.insert(cmd, "logcat")
          require("overseer").new_task({ cmd = cmd, name = "adb logcat" }):start()
        end,
        desc = "adb logcat",
      },
      {
        "<leader>ms",
        function()
          require("config.project_tools").pick_ios_simulator(function(udid)
            if udid then
              vim.notify("iOS simulator: " .. udid, vim.log.levels.INFO, { title = "mobile" })
            end
          end)
        end,
        desc = "Pick/boot iOS simulator",
      },
      {
        "<leader>mx",
        function()
          require("overseer").run_task({ name = "^xcodebuild" })
        end,
        desc = "Xcode tasks",
      },
      {
        "<leader>mk",
        function()
          local tools = require("config.project_tools")
          local overseer = require("overseer")
          local ws = tools.discover_workspaces(vim.fn.expand("%:p:h"))
          local g = ws.gradle[1]
          if not g or not g.kmp then
            vim.notify("No KMP Gradle project nearby", vim.log.levels.WARN, { title = "mobile" })
            return
          end
          local choices = {
            { label = "jvmRun", task = "jvmRun" },
            { label = "run", task = "run" },
            { label = "installDebug", task = "installDebug" },
            { label = "allTests", task = "allTests" },
            { label = "jvmTest", task = "jvmTest" },
            { label = "testAndroidHostTest", task = "testAndroidHostTest" },
          }
          vim.ui.select(choices, {
            prompt = "KMP task",
            format_item = function(c)
              return c.label
            end,
          }, function(choice)
            if not choice then
              return
            end
            local cmd = tools.gradle_cmd(g.root)
            local task = choice.task
            if choice.task == "installDebug" and g.current_module then
              task = ":" .. g.current_module:gsub("/", ":") .. ":installDebug"
            end
            table.insert(cmd, task)
            local env = {}
            if vim.g.android_serial then
              env.ANDROID_SERIAL = vim.g.android_serial
            end
            overseer
              .new_task({
                cmd = cmd,
                cwd = g.root,
                env = env,
                name = "gradle " .. task,
                components = require("config.task_errors").components("gradle"),
              })
              :start()
          end)
        end,
        desc = "KMP quick tasks",
      },
    },
  },
}
