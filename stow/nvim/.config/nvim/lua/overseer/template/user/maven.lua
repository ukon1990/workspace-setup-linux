local overseer = require("overseer")
local tools = require("config.project_tools")
local task_errors = require("config.task_errors")

---@type overseer.TemplateFileProvider
return {
  cache_key = function(opts)
    return tools.git_root(opts.dir)
  end,
  condition = {
    callback = function(opts)
      local ws = tools.discover_workspaces(opts.dir)
      return #ws.maven > 0
    end,
  },
  generator = function(opts, cb)
    local ws = tools.discover_workspaces(opts.dir)
    local ret = {}
    local goals = {
      { "compile", { overseer.TAG.BUILD }, 35 },
      { "package", { overseer.TAG.BUILD }, 30 },
      { "test", { overseer.TAG.TEST }, 40 },
      { "verify", { overseer.TAG.TEST }, 42 },
      { "clean", { overseer.TAG.CLEAN }, 55 },
    }

    for _, m in ipairs(ws.maven) do
      local cmd_base = tools.maven_cmd(m.dir)
      for _, g in ipairs(goals) do
        local goal = g[1]
        table.insert(ret, {
          name = string.format("mvn %s (%s)", goal, m.label),
          tags = g[2],
          priority = m.proximate and g[3] or (g[3] + 20),
          builder = function()
            local cmd = vim.deepcopy(cmd_base)
            table.insert(cmd, goal)
            return {
              cmd = cmd,
              cwd = m.dir,
              name = string.format("mvn %s (%s)", goal, m.label),
              components = task_errors.components("maven"),
            }
          end,
        })
      end
    end

    cb(ret)
  end,
}
