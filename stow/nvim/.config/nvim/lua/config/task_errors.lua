-- Errorformat definitions shared by custom Overseer task templates.

local M = {}

local common = {
  "%E%f:%l:%c: error: %m",
  "%W%f:%l:%c: warning: %m",
  "%E%f:%l: error: %m",
  "%W%f:%l: warning: %m",
}

local formats = {
  gradle = {
    "%Ee: file\\://%f:%l:%c %m",
    "%Ww: file\\://%f:%l:%c %m",
    "%Ee: %f: (%l\\, %c): %m",
    "%Ww: %f: (%l\\, %c): %m",
    "%E[ERROR] %f:[%l\\,%c] %m",
    "%W[WARNING] %f:[%l\\,%c] %m",
  },
  maven = {
    "%E[ERROR] %f:[%l\\,%c] %m",
    "%W[WARNING] %f:[%l\\,%c] %m",
  },
  npm = {
    "%E%f(%l\\,%c): error %m",
    "%W%f(%l\\,%c): warning %m",
    "%E%f:%l:%c - error %m",
    "%W%f:%l:%c - warning %m",
    "%E%f:%l:%c: error %m",
    "%W%f:%l:%c: warning %m",
  },
  dotnet = {
    "%E%f(%l\\,%c): error %m",
    "%W%f(%l\\,%c): warning %m",
    "%E%f(%l): error %m",
    "%W%f(%l): warning %m",
  },
  xcode = {
    "%E%f:%l:%c: error: %m",
    "%W%f:%l:%c: warning: %m",
    "%E%f:%l: error: %m",
    "%W%f:%l: warning: %m",
  },
}

---@param kind "gradle"|"maven"|"npm"|"dotnet"|"xcode"
---@return string
function M.errorformat(kind)
  local patterns = vim.list_extend(vim.deepcopy(formats[kind] or {}), common)
  table.insert(patterns, "%-G%.%#")
  return table.concat(patterns, ",")
end

---@param kind "gradle"|"maven"|"npm"|"dotnet"|"xcode"
---@return table
function M.components(kind)
  return {
    {
      "on_output_quickfix",
      errorformat = M.errorformat(kind),
      items_only = true,
      tail = false,
      open = false,
      open_on_match = false,
      open_on_exit = "never",
    },
    "default",
  }
end

return M
