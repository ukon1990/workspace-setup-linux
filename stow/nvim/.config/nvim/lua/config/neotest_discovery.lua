-- Workspace-aware Neotest discovery: seed nested roots, wait until expected
-- adapters are ready, and surface a Tests-rail loading state while scanning.

local M = {}

local GRADLE_MARKERS = {
  "gradlew",
  "gradlew.bat",
  "settings.gradle",
  "settings.gradle.kts",
  "build.gradle",
  "build.gradle.kts",
}

local MAVEN_MARKERS = { "pom.xml", "mvnw", "mvnw.cmd" }

local VITEST_DEPS = {
  "vitest",
  "@vitest/ui",
  "@vitest/coverage-v8",
  "@analogjs/vitest-angular",
}

---@param dir string
---@param names string[]
---@return boolean
local function dir_has_any(dir, names)
  for _, name in ipairs(names) do
    if vim.uv.fs_stat(dir .. "/" .. name) then
      return true
    end
  end
  return false
end

--- Nearest JVM build system for a path (Maven vs Gradle), walking parents.
--- Siblings are independent: a root Gradle module does not claim a Maven child.
---@param path string
---@return "maven"|"gradle"|nil
function M.nearest_jvm_build(path)
  local dir = vim.fn.isdirectory(path) == 1 and path or vim.fs.dirname(path)
  dir = vim.fs.normalize(dir)
  while dir and dir ~= "" do
    if dir_has_any(dir, MAVEN_MARKERS) then
      return "maven"
    end
    if dir_has_any(dir, GRADLE_MARKERS) then
      return "gradle"
    end
    local parent = vim.fs.normalize(vim.fs.dirname(dir))
    if parent == dir then
      break
    end
    dir = parent
  end
  return nil
end

---@param package_json string
---@param names string[]
---@return boolean
function M.package_has_dependency(package_json, names)
  if vim.fn.filereadable(package_json) ~= 1 then
    return false
  end
  local ok, data = pcall(function()
    return vim.json.decode(table.concat(vim.fn.readfile(package_json), "\n"))
  end)
  if not ok or type(data) ~= "table" then
    return false
  end
  local wanted = {}
  for _, name in ipairs(names) do
    wanted[name] = true
  end
  for _, field in ipairs({ "dependencies", "devDependencies" }) do
    local deps = data[field]
    if type(deps) == "table" then
      for key, _ in pairs(deps) do
        if wanted[key] then
          return true
        end
      end
    end
  end
  if type(data.scripts) == "table" then
    for _, script in pairs(data.scripts) do
      if type(script) == "string" then
        for _, name in ipairs(names) do
          if script:find(name, 1, true) then
            return true
          end
        end
      end
    end
  end
  return false
end

---@param dir string
---@return boolean
function M.npm_has_jest(dir)
  return M.package_has_dependency(dir .. "/package.json", { "jest", "@jest/globals" })
end

---@param dir string
---@return boolean
function M.npm_has_react_scripts(dir)
  return M.package_has_dependency(dir .. "/package.json", { "react-scripts" })
end

---@param dir string
---@return boolean
function M.npm_has_vitest(dir)
  return M.package_has_dependency(dir .. "/package.json", VITEST_DEPS)
end

---@param dir string
---@return boolean
function M.npm_is_js_test_package(dir)
  return M.npm_has_vitest(dir) or M.npm_has_jest(dir) or M.npm_has_react_scripts(dir)
end

--- Walk up package.json dirs until one declares Vitest (incl. nested lib packages).
---@param path string
---@return string|nil
function M.nearest_vitest_package(path)
  local dir = vim.fn.isdirectory(path) == 1 and path or vim.fs.dirname(path)
  dir = vim.fs.normalize(dir)
  while dir and dir ~= "" do
    if vim.uv.fs_stat(dir .. "/package.json") and M.npm_has_vitest(dir) then
      return dir
    end
    local parent = vim.fs.normalize(vim.fs.dirname(dir))
    if parent == dir then
      break
    end
    dir = parent
  end
  return nil
end

--- Filename patterns shared by Jest/Vitest discovery.
---@param file_path string|nil
---@return boolean
function M.is_js_test_file(file_path)
  if not file_path or file_path == "" then
    return false
  end
  if file_path:find("__tests__", 1, true) then
    return true
  end
  for _, kind in ipairs({ "e2e", "spec", "test" }) do
    for _, ext in ipairs({ "js", "jsx", "coffee", "ts", "tsx" }) do
      if file_path:match("%." .. kind .. "%." .. ext .. "$") then
        return true
      end
    end
  end
  return false
end

---@param dir string
---@return boolean
function M.has_cargo(dir)
  return vim.fs.find("Cargo.toml", { upward = true, path = dir, limit = 1 })[1] ~= nil
end

--- Label for summary headers / Overseer tabs, e.g. "neotest-maven · backend".
---@param adapter_id string
---@return string
function M.adapter_header_label(adapter_id)
  local kind, root = adapter_id:match("^([^:]+):(.*)$")
  if not kind then
    return adapter_id
  end
  if not root or root == "" then
    return kind
  end
  local folder = vim.fn.fnamemodify(vim.fs.normalize(root), ":t")
  if folder == "" or folder == "/" then
    return kind
  end
  return kind .. " · " .. folder
end

--- Dock tab label for a runner cwd, e.g. "tests: frontend".
---@param cwd string|nil
---@return string
function M.runner_tab_label(cwd)
  if not cwd or cwd == "" then
    return "tests"
  end
  local folder = vim.fn.fnamemodify(vim.fs.normalize(cwd), ":t")
  if folder == "" or folder == "/" then
    return "tests"
  end
  return "tests: " .. folder
end

--- Adapter-id prefixes we expect from workspace scan.
---@param ws table
---@return table<string, boolean>
function M.expected_adapter_kinds(ws)
  local expected = {}
  if ws.maven and #ws.maven > 0 then
    expected["neotest-maven"] = true
  end
  if ws.gradle and #ws.gradle > 0 then
    expected["gradle-test"] = true
  end
  for _, pkg in ipairs(ws.npm or {}) do
    if M.npm_has_vitest(pkg.dir) then
      expected["neotest-vitest"] = true
    elseif M.npm_has_jest(pkg.dir) or M.npm_has_react_scripts(pkg.dir) then
      expected["neotest-jest"] = true
    end
  end
  if M.has_cargo(ws.git_root or vim.uv.cwd()) then
    expected["neotest-rust"] = true
  end
  return expected
end

---@param adapter_id string
---@return string
local function adapter_kind(adapter_id)
  return vim.split(adapter_id, ":", { plain = true })[1] or adapter_id
end

--- True when the adapter root tree has children (same rule as Client:get_adapters).
---@param adapter_id string
---@return boolean
function M.adapter_has_positions(adapter_id)
  local ok, tree = pcall(function()
    return require("neotest").state.positions(adapter_id)
  end)
  return ok and tree ~= nil and #tree:children() > 0
end

---@param adapter_ids string[]
---@return string[]
function M.runnable_adapter_ids(adapter_ids)
  local runnable = {}
  for _, id in ipairs(adapter_ids or {}) do
    if M.adapter_has_positions(id) then
      runnable[#runnable + 1] = id
    end
  end
  return runnable
end

---@param adapter_ids string[]
---@param expected table<string, boolean>
---@return boolean
function M.expected_kinds_present(adapter_ids, expected)
  if not next(expected) then
    return #adapter_ids > 0
  end
  local found = {}
  for _, id in ipairs(adapter_ids) do
    found[adapter_kind(id)] = true
  end
  for kind, _ in pairs(expected) do
    if not found[kind] then
      return false
    end
  end
  return true
end

--- Like expected_kinds_present, but each kind must have a non-empty position tree.
---@param adapter_ids string[]
---@param expected table<string, boolean>
---@return boolean
function M.expected_kinds_ready(adapter_ids, expected)
  if not next(expected) then
    return #M.runnable_adapter_ids(adapter_ids) > 0
  end
  local found = {}
  for _, id in ipairs(adapter_ids) do
    if M.adapter_has_positions(id) then
      found[adapter_kind(id)] = true
    end
  end
  for kind, _ in pairs(expected) do
    if not found[kind] then
      return false
    end
  end
  return true
end

---@param adapter_ids string[]
---@return string
function M.positions_signature(adapter_ids)
  local neotest = require("neotest")
  local parts = {}
  local ids = vim.deepcopy(adapter_ids)
  table.sort(ids)
  for _, adapter_id in ipairs(ids) do
    local count = 0
    local tree = neotest.state.positions(adapter_id)
    if tree then
      for _ in tree:iter() do
        count = count + 1
      end
    end
    parts[#parts + 1] = adapter_id .. "=" .. tostring(count)
  end
  return table.concat(parts, "\n")
end

---@param message string|nil
function M.set_loading(message)
  require("config.tool_panel").set_tests_status(message)
end

--- Seed Neotest adapters for every Maven / Gradle / npm root under the workspace.
--- Nested package roots are scanned before the git root so Vitest/Maven register.
---@param client table
---@param anchor? string
---@return table workspace
function M.refresh_adapters(client, anchor)
  local tools = require("config.project_tools")
  local ws = tools.discover_workspaces(anchor or vim.uv.cwd())
  local roots = {}
  for _, m in ipairs(ws.maven or {}) do
    roots[#roots + 1] = m.dir
  end
  for _, g in ipairs(ws.gradle or {}) do
    roots[#roots + 1] = g.root
  end
  for _, pkg in ipairs(ws.npm or {}) do
    -- Skip bare library packages (e.g. ethereal-ui) that have no test runner.
    if M.npm_is_js_test_package(pkg.dir) then
      roots[#roots + 1] = pkg.dir
    end
  end
  roots[#roots + 1] = ws.git_root

  local seen = {}
  for _, root in ipairs(roots) do
    if root and not seen[root] then
      seen[root] = true
      -- Private client API: re-scan adapters for this project root.
      client:_update_adapters(root)
    end
  end
  return ws
end

---@class neotest_discovery.WaitOpts
---@field path? string
---@field timeout_ms? integer
---@field stable_ms? integer
---@field on_ready? fun(adapter_ids: string[])

--- Wait until expected workspace adapters have stable position trees.
---@param client table
---@param opts? neotest_discovery.WaitOpts
function M.ensure_discovered(client, opts)
  opts = opts or {}
  local neotest = require("neotest")
  local nio = require("nio")
  local timeout_ms = opts.timeout_ms or 45000
  local stable_ms = opts.stable_ms or 600
  local started = vim.uv.now()
  local last_signature
  local stable_since
  local on_ready = opts.on_ready or function() end

  M.set_loading("Discovering tests…")

  nio.run(function()
    client:get_adapters()
    local ws = M.refresh_adapters(client, opts.path or vim.uv.cwd())
    local expected = M.expected_adapter_kinds(ws)

    while true do
      local adapter_ids = neotest.state.adapter_ids()
      local signature = M.positions_signature(adapter_ids)
      local elapsed = vim.uv.now() - started
      local kinds_ready = M.expected_kinds_ready(adapter_ids, expected)
      local runnable = M.runnable_adapter_ids(adapter_ids)

      if signature ~= last_signature then
        last_signature = signature
        stable_since = vim.uv.now()
        local pending = {}
        for kind, _ in pairs(expected) do
          local found = false
          for _, id in ipairs(runnable) do
            if adapter_kind(id) == kind then
              found = true
              break
            end
          end
          if not found then
            pending[#pending + 1] = kind
          end
        end
        if #pending > 0 then
          M.set_loading(("Discovering tests… (%s)"):format(table.concat(pending, ", ")))
        else
          M.set_loading(("Discovering tests… %d suite(s)"):format(#runnable))
        end
      end

      local stable = stable_since and (vim.uv.now() - stable_since) >= stable_ms
      if #runnable > 0 and kinds_ready and stable then
        M.set_loading(nil)
        vim.schedule(function()
          on_ready(runnable)
        end)
        return
      end

      if elapsed >= timeout_ms then
        M.set_loading(nil)
        if #runnable > 0 then
          vim.schedule(function()
            on_ready(runnable)
          end)
        elseif #adapter_ids > 0 then
          vim.schedule(function()
            on_ready(M.runnable_adapter_ids(adapter_ids))
          end)
        else
          vim.notify("No test suites discovered", vim.log.levels.INFO, { title = "neotest" })
        end
        return
      end

      nio.sleep(150)
    end
  end)
end

--- Wait until expected adapters are ready, then invoke on_ready (typically to run suites).
---@param client table
---@param opts neotest_discovery.WaitOpts
function M.wait_then_run(client, opts)
  opts = opts or {}
  M.ensure_discovered(client, {
    path = opts.path,
    timeout_ms = opts.timeout_ms,
    stable_ms = opts.stable_ms,
    on_ready = opts.on_ready,
  })
end

return M
