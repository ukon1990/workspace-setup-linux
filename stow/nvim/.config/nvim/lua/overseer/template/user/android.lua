local overseer = require("overseer")
local tools = require("config.project_tools")
local task_errors = require("config.task_errors")
local task_errors = require("config.task_errors")

---@type overseer.TemplateFileProvider
return {
  condition = {
    callback = function()
      return vim.fn.executable("adb") == 1
    end,
  },
  generator = function(opts, cb)
    local ws = tools.discover_workspaces(opts.dir)
    local ret = {
      {
        name = "adb devices",
        priority = 80,
        builder = function()
          return { cmd = { "adb", "devices", "-l" } }
        end,
      },
      {
        name = "adb logcat",
        priority = 75,
        builder = function()
          local cmd = { "adb" }
          if vim.g.android_serial then
            vim.list_extend(cmd, { "-s", vim.g.android_serial })
          end
          table.insert(cmd, "logcat")
          return { cmd = cmd }
        end,
      },
    }

    for _, g in ipairs(ws.gradle) do
      if g.android then
        local mod = g.current_module
        local task = mod and (":" .. mod:gsub("/", ":") .. ":installDebug") or "installDebug"
        table.insert(ret, {
          name = string.format("adb+gradle %s (%s)", task, g.label),
          tags = { overseer.TAG.RUN },
          priority = g.proximate and 27 or 47,
          builder = function()
            local function build(serial)
              local cmd = tools.gradle_cmd(g.root)
              table.insert(cmd, task)
              local env = {}
              if serial then
                env.ANDROID_SERIAL = serial
              end
              return {
                cmd = cmd,
                cwd = g.root,
                env = env,
                name = string.format("gradle %s (%s)", task, g.label),
                components = task_errors.components("gradle"),
                components = task_errors.components("gradle"),
              }
            end

            if vim.g.android_serial then
              return build(vim.g.android_serial)
            end

            -- Sync pick then start: return a placeholder that picks in on_pre_start via components
            -- Simpler: pick synchronously is not possible; use stored or prompt via params.
            return build(nil)
          end,
        })
      end
    end

    cb(ret)
  end,
}
