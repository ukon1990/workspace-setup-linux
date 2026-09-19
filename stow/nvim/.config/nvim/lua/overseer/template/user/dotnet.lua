local overseer = require("overseer")
local tools = require("config.project_tools")
local task_errors = require("config.task_errors")

---@param proj table
---@return integer
local function base_priority(proj)
  if proj.primary then
    return 30
  end
  if proj.containing then
    return 50
  end
  return 70
end

---@type overseer.TemplateFileProvider
return {
  cache_key = function(opts)
    local nearest = vim.fs.find(function(name)
      return name:match("%.csproj$") or name:match("%.fsproj$") or name:match("%.sln$")
    end, { upward = true, path = opts.dir, type = "file", limit = 1 })[1]
    return (nearest or tools.git_root(opts.dir)) .. "\0" .. tools.git_root(opts.dir)
  end,
  condition = {
    callback = function(opts)
      if vim.fn.executable("dotnet") ~= 1 then
        return false, 'Command "dotnet" not found'
      end
      local ws = tools.discover_workspaces(opts.dir)
      return #ws.dotnet > 0
    end,
  },
  generator = function(opts, cb)
    local ws = tools.discover_workspaces(opts.dir)
    local ret = {}

    for _, proj in ipairs(ws.dotnet) do
      local base = base_priority(proj)

      local function add(args, tags, priority)
        local action = table.concat(args, " ")
        table.insert(ret, {
          name = string.format("dotnet %s (%s)", action, proj.label),
          tags = tags,
          priority = priority,
          builder = function()
            local cmd = { "dotnet" }
            vim.list_extend(cmd, args)
            table.insert(cmd, proj.path)
            return {
              cmd = cmd,
              cwd = proj.dir,
              name = string.format("dotnet %s (%s)", args[1], proj.label),
              components = task_errors.components("dotnet"),
            }
          end,
        })
      end

      add({ "restore" }, { overseer.TAG.BUILD }, base + 15)
      add({ "build" }, { overseer.TAG.BUILD }, base)
      add({ "test" }, { overseer.TAG.TEST }, base + 5)
      add({ "clean" }, { overseer.TAG.CLEAN }, base + 25)

      if proj.kind ~= "sln" then
        table.insert(ret, {
          name = string.format("dotnet run (%s)", proj.label),
          tags = { overseer.TAG.RUN },
          priority = base - 5,
          builder = function()
            return {
              cmd = { "dotnet", "run", "--project", proj.path },
              cwd = proj.dir,
              name = string.format("dotnet run (%s)", proj.label),
              components = task_errors.components("dotnet"),
            }
          end,
        })
        table.insert(ret, {
          name = string.format("dotnet watch run (%s)", proj.label),
          tags = { overseer.TAG.RUN },
          priority = base - 4,
          builder = function()
            return {
              cmd = { "dotnet", "watch", "run", "--project", proj.path },
              cwd = proj.dir,
              name = string.format("dotnet watch run (%s)", proj.label),
              components = task_errors.components("dotnet"),
            }
          end,
        })
      end
    end

    cb(ret)
  end,
}
