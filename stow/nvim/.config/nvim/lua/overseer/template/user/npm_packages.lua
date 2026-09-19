local overseer = require("overseer")
local tools = require("config.project_tools")
local task_errors = require("config.task_errors")

local RUN_SCRIPTS = { dev = true, start = true }
local TEST_SCRIPTS = { test = true, ["test:unit"] = true, ["test:e2e"] = true, ["test:ci"] = true }

---@param path string
---@return table|nil
local function load_json(path)
  local ok, data = pcall(function()
    return vim.json.decode(table.concat(vim.fn.readfile(path), "\n"))
  end)
  if ok and type(data) == "table" then
    return data
  end
  return nil
end

---@param pkg table
---@param script string
---@return integer
local function priority_for(pkg, script)
  local base = 70
  if RUN_SCRIPTS[script] then
    base = 25
  elseif TEST_SCRIPTS[script] or script:match("^test") then
    base = 35
  end
  if pkg.primary then
    return base
  end
  if pkg.containing then
    return base + 25
  end
  return base + 45
end

---@type overseer.TemplateFileProvider
return {
  -- Bust cache when the nearest package changes (frontend vs root, etc.)
  cache_key = function(opts)
    return (tools.nearest_npm_dir(opts.dir) or tools.git_root(opts.dir)) .. "\0" .. tools.git_root(opts.dir)
  end,
  condition = {
    callback = function(opts)
      local ws = tools.discover_workspaces(opts.dir)
      return #ws.npm > 0
    end,
  },
  generator = function(opts, cb)
    local ws = tools.discover_workspaces(opts.dir)
    local ret = {}
    local has_nested_primary = false
    for _, pkg in ipairs(ws.npm) do
      if pkg.primary and pkg.label ~= "." then
        has_nested_primary = true
        break
      end
    end

    for _, pkg in ipairs(ws.npm) do
      -- When editing inside frontend/, skip bare root workspace package.json scripts
      -- so tests/dev don't accidentally run from `.`
      if has_nested_primary and pkg.label == "." and not pkg.primary then
        goto continue
      end

      if vim.fn.executable(pkg.manager) == 1 then
        local data = load_json(pkg.path)
        local scripts = data and data.scripts or {}
        local label = pkg.label

        for _, script in ipairs({ "dev", "start" }) do
          if scripts[script] then
            table.insert(ret, {
              name = string.format("%s run %s (%s)", pkg.manager, script, label),
              desc = scripts[script],
              priority = priority_for(pkg, script),
              tags = { overseer.TAG.RUN },
              builder = function()
                return {
                  cmd = { pkg.manager, "run", script },
                  cwd = pkg.dir,
                  name = string.format("%s run %s (%s)", pkg.manager, script, label),
                  components = task_errors.components("npm"),
                }
              end,
            })
          end
        end

        for script, cmd in pairs(scripts) do
          if not RUN_SCRIPTS[script] then
            local tags = nil
            if TEST_SCRIPTS[script] or script:match("^test") then
              tags = { overseer.TAG.TEST }
            end
            table.insert(ret, {
              name = string.format("%s run %s (%s)", pkg.manager, script, label),
              desc = cmd,
              priority = priority_for(pkg, script),
              tags = tags,
              builder = function()
                return {
                  cmd = { pkg.manager, "run", script },
                  cwd = pkg.dir,
                  name = string.format("%s run %s (%s)", pkg.manager, script, label),
                  components = task_errors.components("npm"),
                }
              end,
            })
          end
        end

        table.insert(ret, {
          name = string.format("%s install (%s)", pkg.manager, label),
          priority = pkg.primary and 55 or 85,
          builder = function()
            return {
              cmd = { pkg.manager, "install" },
              cwd = pkg.dir,
              name = string.format("%s install (%s)", pkg.manager, label),
              components = task_errors.components("npm"),
            }
          end,
        })
      end
      ::continue::
    end

    cb(ret)
  end,
}
