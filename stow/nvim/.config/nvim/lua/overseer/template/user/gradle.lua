local overseer = require("overseer")
local tools = require("config.project_tools")
local task_errors = require("config.task_errors")

---@param g table
---@param task string
---@param opts { tags?: string[], priority?: integer, module?: string|nil }
---@return overseer.TemplateDefinition
local function gradle_task(g, task, opts)
  opts = opts or {}
  local module = opts.module
  local gradle_task = module and (":" .. module:gsub("/", ":") .. ":" .. task) or task
  local label = module and (g.label .. "/" .. module) or g.label
  return {
    name = string.format("gradle %s (%s)", gradle_task, label),
    tags = opts.tags,
    priority = opts.priority or (g.proximate and 45 or 65),
    builder = function()
      local cmd = tools.gradle_cmd(g.root)
      table.insert(cmd, gradle_task)
      local env = {}
      if vim.g.android_serial then
        env.ANDROID_SERIAL = vim.g.android_serial
      end
      return {
        cmd = cmd,
        cwd = g.root,
        env = env,
        name = string.format("gradle %s (%s)", gradle_task, label),
        components = task_errors.components("gradle"),
      }
    end,
  }
end

---@type overseer.TemplateFileProvider
return {
  cache_key = function(opts)
    local ws = tools.discover_workspaces(opts.dir)
    local g = ws.gradle[1]
    local mod = g and g.current_module or ""
    return tools.git_root(opts.dir) .. "\0" .. (g and g.root or "") .. "\0" .. mod
  end,
  condition = {
    callback = function(opts)
      local ws = tools.discover_workspaces(opts.dir)
      return #ws.gradle > 0
    end,
  },
  generator = function(opts, cb)
    local ws = tools.discover_workspaces(opts.dir)
    local ret = {}

    for _, g in ipairs(ws.gradle) do
      local root_tasks = {
        { "build", { overseer.TAG.BUILD }, 30 },
        { "assemble", { overseer.TAG.BUILD }, 35 },
        { "clean", { overseer.TAG.CLEAN }, 55 },
        { "test", { overseer.TAG.TEST }, 40 },
      }
      for _, t in ipairs(root_tasks) do
        table.insert(ret, gradle_task(g, t[1], { tags = t[2], priority = g.proximate and t[3] or (t[3] + 20) }))
      end

      if g.kmp then
        table.insert(
          ret,
          gradle_task(g, "allTests", { tags = { overseer.TAG.TEST }, priority = g.proximate and 38 or 58 })
        )
        if g.jvm then
          table.insert(
            ret,
            gradle_task(g, "jvmTest", { tags = { overseer.TAG.TEST }, priority = g.proximate and 37 or 57 })
          )
          table.insert(
            ret,
            gradle_task(g, "jvmRun", { tags = { overseer.TAG.RUN }, priority = g.proximate and 25 or 45 })
          )
          table.insert(
            ret,
            gradle_task(g, "run", { tags = { overseer.TAG.RUN }, priority = g.proximate and 26 or 46 })
          )
        end
        table.insert(
          ret,
          gradle_task(g, "testAndroidHostTest", {
            tags = { overseer.TAG.TEST },
            priority = g.proximate and 39 or 59,
          })
        )
      end

      if g.android then
        local android_tasks = {
          { "assembleDebug", { overseer.TAG.BUILD }, 32 },
          { "installDebug", { overseer.TAG.RUN }, 28 },
          { "uninstallDebug", nil, 70 },
          { "connectedDebugAndroidTest", { overseer.TAG.TEST }, 42 },
        }
        local mod = g.current_module
        for _, t in ipairs(android_tasks) do
          table.insert(
            ret,
            gradle_task(g, t[1], {
              tags = t[2],
              priority = g.proximate and t[3] or (t[3] + 20),
              module = mod,
            })
          )
          if not mod then
            -- also root-level without module prefix
          end
        end
      end

      -- Module-scoped build/test for current module or all (capped)
      local mods = g.modules
      if g.current_module then
        mods = { g.current_module }
      elseif #mods > 12 then
        mods = vim.list_slice(mods, 1, 12)
      end
      for _, mod in ipairs(mods) do
        table.insert(
          ret,
          gradle_task(g, "build", {
            tags = { overseer.TAG.BUILD },
            priority = g.proximate and 48 or 68,
            module = mod,
          })
        )
        table.insert(
          ret,
          gradle_task(g, "test", {
            tags = { overseer.TAG.TEST },
            priority = g.proximate and 49 or 69,
            module = mod,
          })
        )
      end
    end

    cb(ret)
  end,
}
