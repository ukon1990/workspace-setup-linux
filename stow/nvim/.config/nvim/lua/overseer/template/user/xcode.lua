local overseer = require("overseer")
local tools = require("config.project_tools")
local task_errors = require("config.task_errors")

---@param project { path: string, kind: string, label: string }
---@param scheme string
---@param action string
---@param tags string[]|nil
---@param priority integer
---@return overseer.TemplateDefinition
local function xcode_task(project, scheme, action, tags, priority)
  local flag = project.kind == "workspace" and "-workspace" or "-project"
  return {
    name = string.format("xcodebuild %s %s (%s)", action, scheme, project.label),
    tags = tags,
    priority = priority,
    builder = function()
      local cmd = {
        "xcodebuild",
        flag,
        project.path,
        "-scheme",
        scheme,
      }
      if action == "build" then
        table.insert(cmd, "build")
      elseif action == "test" then
        table.insert(cmd, "test")
      elseif action == "run" then
        vim.list_extend(cmd, { "-destination", "platform=iOS Simulator,name=iPhone 16", "build" })
      end
      return {
        cmd = cmd,
        cwd = vim.fs.dirname(project.path),
        name = string.format("xcodebuild %s %s", action, scheme),
        components = task_errors.components("xcode"),
      }
    end,
  }
end

---@type overseer.TemplateFileProvider
return {
  condition = {
    callback = function()
      return vim.fn.has("macunix") == 1 and vim.fn.executable("xcodebuild") == 1
    end,
  },
  cache_key = function(opts)
    return tools.git_root(opts.dir)
  end,
  generator = function(opts, cb)
    local ws = tools.discover_workspaces(opts.dir)
    if #ws.xcode == 0 then
      return cb({})
    end

    local ret = {}

    local pending = 0
    local function finish()
      pending = pending - 1
      if pending <= 0 then
        cb(ret)
      end
    end

    for _, project in ipairs(ws.xcode) do
      if project.kind == "spm" then
        table.insert(ret, {
          name = string.format("swift build (%s)", project.label),
          tags = { overseer.TAG.BUILD },
          priority = project.proximate and 35 or 55,
          builder = function()
            return {
              cmd = { "swift", "build" },
              cwd = project.path,
              components = task_errors.components("xcode"),
            }
          end,
        })
        table.insert(ret, {
          name = string.format("swift test (%s)", project.label),
          tags = { overseer.TAG.TEST },
          priority = project.proximate and 40 or 60,
          builder = function()
            return {
              cmd = { "swift", "test" },
              cwd = project.path,
              components = task_errors.components("xcode"),
            }
          end,
        })
      else
        pending = pending + 1
        local flag = project.kind == "workspace" and "-workspace" or "-project"
        vim.system({ "xcodebuild", "-list", flag, project.path, "-json" }, { text = true }, function(obj)
          vim.schedule(function()
            if obj.code == 0 and obj.stdout and #obj.stdout > 0 then
              local ok, data = pcall(vim.json.decode, obj.stdout)
              local schemes = {}
              if ok and type(data) == "table" then
                local info = data.project or data.workspace or {}
                schemes = info.schemes or {}
              end
              for _, scheme in ipairs(schemes) do
                table.insert(
                  ret,
                  xcode_task(project, scheme, "build", { overseer.TAG.BUILD }, project.proximate and 34 or 54)
                )
                table.insert(
                  ret,
                  xcode_task(project, scheme, "test", { overseer.TAG.TEST }, project.proximate and 41 or 61)
                )
                table.insert(
                  ret,
                  xcode_task(project, scheme, "run", { overseer.TAG.RUN }, project.proximate and 29 or 49)
                )
              end
            end
            finish()
          end)
        end)
      end
    end

    if pending == 0 then
      cb(ret)
    end
  end,
}
