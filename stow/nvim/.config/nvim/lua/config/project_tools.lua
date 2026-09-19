-- Monorepo-aware project / device helpers for overseer templates.

local M = {}

local SKIP_DIRS = {
  [".git"] = true,
  ["node_modules"] = true,
  ["build"] = true,
  ["target"] = true,
  [".gradle"] = true,
  ["dist"] = true,
  [".next"] = true,
  ["coverage"] = true,
  ["vendor"] = true,
  ["bin"] = true,
  ["obj"] = true,
}

local LOCKFILES = {
  { mgr = "bun", files = { "bun.lockb", "bun.lock" } },
  { mgr = "pnpm", files = { "pnpm-lock.yaml" } },
  { mgr = "yarn", files = { "yarn.lock" } },
  { mgr = "npm", files = { "package-lock.json" } },
}

local MARKER_FILES = {
  { mgr = "bun", files = { "bunfig.toml" } },
  { mgr = "pnpm", files = { "pnpm-workspace.yaml" } },
}

local MAX_SCAN_DEPTH = 4

-- Results are grouped by repository and then by the active path. This avoids
-- repeating the same recursive monorepo scan for every Overseer provider while
-- still preserving path-sensitive priorities/current-module selection.
---@type table<string, table<string, table>>
local discovery_cache = {}
local cache_stats = { hits = 0, misses = 0 }
local cache_autocmds = false

---@param path string
---@return string
local function normalize(path)
  return vim.fs.normalize(path)
end

---@param dir string|nil
---@return string
function M.git_root(dir)
  dir = normalize(dir or vim.fn.getcwd())
  local found = vim.fs.find(".git", { upward = true, path = dir, type = "directory" })[1]
    or vim.fs.find(".git", { upward = true, path = dir, type = "file" })[1]
  if found then
    return normalize(vim.fs.dirname(found))
  end
  return dir
end

---@param root? string
function M.clear_cache(root)
  if root then
    discovery_cache[normalize(root)] = nil
  else
    discovery_cache = {}
  end
end

local function setup_cache_invalidation()
  if cache_autocmds then
    return
  end
  cache_autocmds = true
  local group = vim.api.nvim_create_augroup("ProjectToolsCache", { clear = true })
  vim.api.nvim_create_autocmd("DirChanged", {
    group = group,
    callback = function()
      M.clear_cache()
    end,
  })
  vim.api.nvim_create_autocmd("BufWritePost", {
    group = group,
    pattern = {
      "package.json",
      "package-lock.json",
      "pnpm-lock.yaml",
      "pnpm-workspace.yaml",
      "yarn.lock",
      "bun.lock",
      "bun.lockb",
      "settings.gradle",
      "settings.gradle.kts",
      "build.gradle",
      "build.gradle.kts",
      "pom.xml",
      "*.csproj",
      "*.fsproj",
      "*.sln",
      "Package.swift",
    },
    callback = function()
      M.clear_cache()
    end,
  })
end

---@param from string
---@param to string
---@return string
function M.relpath(from, to)
  from = normalize(from)
  to = normalize(to)
  if to == from then
    return "."
  end
  local prefix = from:sub(-1) == "/" and from or (from .. "/")
  if to:sub(1, #prefix) == prefix then
    return to:sub(#prefix + 1)
  end
  return vim.fn.fnamemodify(to, ":t")
end

---@param dir string
---@return string|nil
function M.find_gradle_root(dir)
  dir = normalize(dir)
  local markers = { "settings.gradle.kts", "settings.gradle", "gradlew" }
  for _, marker in ipairs(markers) do
    local hit = vim.fs.find(marker, { upward = true, path = dir, type = "file" })[1]
    if hit then
      return normalize(vim.fs.dirname(hit))
    end
  end
  return nil
end

---@param root string
---@return string[]
function M.gradle_cmd(root)
  local wrapper = root .. "/gradlew"
  if vim.fn.executable(wrapper) == 1 or vim.fn.filereadable(wrapper) == 1 then
    return { wrapper }
  end
  return { "gradle" }
end

---@param root string
---@return string[]
function M.gradle_modules(root)
  local modules = {}
  local settings
  for _, name in ipairs({ "settings.gradle.kts", "settings.gradle" }) do
    local path = root .. "/" .. name
    if vim.fn.filereadable(path) == 1 then
      settings = path
      break
    end
  end
  if not settings then
    return modules
  end

  local content = table.concat(vim.fn.readfile(settings), "\n")
  local seen = {}
  for block in content:gmatch("include%s*%(([^)]+)%)") do
    for name in block:gmatch('["\']([^"\']+)["\']') do
      local mod = name:gsub("^:", ""):gsub(":", "/")
      if not seen[mod] then
        seen[mod] = true
        table.insert(modules, mod)
      end
    end
  end
  return modules
end

---@param modules string[]
---@param path string
---@param root string
---@return string|nil
function M.module_for_path(modules, path, root)
  path = normalize(path)
  root = normalize(root)
  local best, best_len
  for _, mod in ipairs(modules) do
    local mod_path = normalize(root .. "/" .. mod)
    if path == mod_path or path:sub(1, #mod_path + 1) == mod_path .. "/" then
      if not best_len or #mod_path > best_len then
        best = mod
        best_len = #mod_path
      end
    end
  end
  return best
end

---@param paths string[]
---@return boolean
local function content_matches_any(paths, needles)
  for _, path in ipairs(paths) do
    if vim.fn.filereadable(path) == 1 then
      local content = table.concat(vim.fn.readfile(path), "\n")
      for _, needle in ipairs(needles) do
        if content:find(needle, 1, true) then
          return true
        end
      end
    end
  end
  return false
end

---@param root string
---@return string[]
local function gradle_build_files(root)
  local files = {}
  for _, name in ipairs({ "build.gradle.kts", "build.gradle" }) do
    local path = root .. "/" .. name
    if vim.fn.filereadable(path) == 1 then
      table.insert(files, path)
    end
  end
  for _, mod in ipairs(M.gradle_modules(root)) do
    for _, name in ipairs({ "build.gradle.kts", "build.gradle" }) do
      local path = root .. "/" .. mod .. "/" .. name
      if vim.fn.filereadable(path) == 1 then
        table.insert(files, path)
      end
    end
  end
  return files
end

---@param root string
---@return boolean
function M.is_kmp(root)
  return content_matches_any(gradle_build_files(root), {
    "kotlinMultiplatform",
    "androidMultiplatformLibrary",
    "org.jetbrains.kotlin.multiplatform",
  })
end

---@param root string
---@param module string|nil
---@return boolean
function M.has_android(root, module)
  local files = {}
  local dirs = { root }
  if module then
    dirs = { root .. "/" .. module }
  else
    for _, mod in ipairs(M.gradle_modules(root)) do
      table.insert(dirs, root .. "/" .. mod)
    end
  end
  for _, dir in ipairs(dirs) do
    for _, name in ipairs({ "build.gradle.kts", "build.gradle" }) do
      local path = dir .. "/" .. name
      if vim.fn.filereadable(path) == 1 then
        table.insert(files, path)
      end
    end
  end
  return content_matches_any(files, {
    "com.android",
    "android {",
    "android{",
    'id("com.android',
    "id('com.android",
  })
end

---@param root string
---@return boolean
function M.has_jvm_target(root)
  return content_matches_any(gradle_build_files(root), { "jvm(", "jvm {" })
end

---@param dir string
---@return string|nil, string|nil
function M.find_maven_root(dir)
  dir = normalize(dir)
  local pom = vim.fs.find("pom.xml", { upward = true, path = dir, type = "file" })[1]
  if not pom then
    return nil, nil
  end
  return normalize(vim.fs.dirname(pom)), normalize(pom)
end

---@param root string
---@return string[]
function M.maven_cmd(root)
  local wrapper = root .. "/mvnw"
  if vim.fn.executable(wrapper) == 1 or vim.fn.filereadable(wrapper) == 1 then
    return { wrapper }
  end
  return { "mvn" }
end

---@param dir string
---@return string|nil
local function lockfile_manager_in_dir(dir)
  for _, entry in ipairs(LOCKFILES) do
    for _, lock in ipairs(entry.files) do
      if vim.uv.fs_stat(dir .. "/" .. lock) then
        return entry.mgr
      end
    end
  end
  for _, entry in ipairs(MARKER_FILES) do
    for _, marker in ipairs(entry.files) do
      if vim.uv.fs_stat(dir .. "/" .. marker) then
        return entry.mgr
      end
    end
  end
  return nil
end

---@param package_json_path string
---@return string|nil
local function package_manager_field(package_json_path)
  if vim.fn.filereadable(package_json_path) ~= 1 then
    return nil
  end
  local ok, data = pcall(function()
    return vim.json.decode(table.concat(vim.fn.readfile(package_json_path), "\n"))
  end)
  if not ok or type(data) ~= "table" or type(data.packageManager) ~= "string" then
    return nil
  end
  -- e.g. "pnpm@9.12.0", "bun@1.1.0"
  local mgr = data.packageManager:match("^([%w]+)")
  if mgr == "npm" or mgr == "pnpm" or mgr == "yarn" or mgr == "bun" then
    return mgr
  end
  return nil
end

---@param mgr string
---@return string
local function resolve_manager_bin(mgr)
  if vim.fn.executable(mgr) == 1 then
    return mgr
  end
  for _, fallback in ipairs({ "npm", "pnpm", "yarn", "bun" }) do
    if fallback ~= mgr and vim.fn.executable(fallback) == 1 then
      return fallback
    end
  end
  return mgr
end

---Detect bun / pnpm / yarn / npm for a package directory.
---Order: nearest package.json "packageManager" → nearest lockfile/marker up to git root → npm.
---@param package_dir string
---@return string manager binary to invoke
function M.package_manager(package_dir)
  package_dir = normalize(package_dir)
  local stop = M.git_root(package_dir)

  local dir = package_dir
  while true do
    local from_field = package_manager_field(dir .. "/package.json")
    if from_field then
      return resolve_manager_bin(from_field)
    end
    local found = lockfile_manager_in_dir(dir)
    if found then
      return resolve_manager_bin(found)
    end
    if dir == stop or dir == "/" then
      break
    end
    local parent = normalize(vim.fs.dirname(dir))
    if parent == dir then
      break
    end
    dir = parent
  end

  return resolve_manager_bin("npm")
end

---@param root string
---@param max_depth integer|nil
---@return string[]
function M.find_npm_packages(root, max_depth)
  root = normalize(root)
  max_depth = max_depth or MAX_SCAN_DEPTH
  local results = {}

  local function walk(dir, depth)
    if depth > max_depth then
      return
    end
    local pkg = dir .. "/package.json"
    if vim.fn.filereadable(pkg) == 1 then
      table.insert(results, normalize(pkg))
    end
    local handle = vim.uv.fs_scandir(dir)
    if not handle then
      return
    end
    while true do
      local name, typ = vim.uv.fs_scandir_next(handle)
      if not name then
        break
      end
      if typ == "directory" and not SKIP_DIRS[name] and name:sub(1, 1) ~= "." then
        walk(dir .. "/" .. name, depth + 1)
      end
    end
  end

  walk(root, 0)
  return results
end

---@param root string
---@return string[]
local function find_gradle_roots_under(root)
  root = normalize(root)
  local roots = {}
  local seen = {}

  local function add(dir)
    dir = normalize(dir)
    if not seen[dir] then
      seen[dir] = true
      table.insert(roots, dir)
    end
  end

  local upward = M.find_gradle_root(root)
  if upward then
    add(upward)
  end

  local function walk(dir, depth)
    if depth > MAX_SCAN_DEPTH then
      return
    end
    if
      vim.fn.filereadable(dir .. "/settings.gradle.kts") == 1
      or vim.fn.filereadable(dir .. "/settings.gradle") == 1
      or vim.fn.filereadable(dir .. "/gradlew") == 1
    then
      add(dir)
    end
    local handle = vim.uv.fs_scandir(dir)
    if not handle then
      return
    end
    while true do
      local name, typ = vim.uv.fs_scandir_next(handle)
      if not name then
        break
      end
      if typ == "directory" and not SKIP_DIRS[name] and name:sub(1, 1) ~= "." then
        walk(dir .. "/" .. name, depth + 1)
      end
    end
  end

  walk(root, 0)
  return roots
end

---@param root string
---@return string[]
local function find_maven_poms_under(root)
  root = normalize(root)
  local results = {}

  local function walk(dir, depth)
    if depth > MAX_SCAN_DEPTH then
      return
    end
    local pom = dir .. "/pom.xml"
    if vim.fn.filereadable(pom) == 1 then
      table.insert(results, normalize(pom))
    end
    local handle = vim.uv.fs_scandir(dir)
    if not handle then
      return
    end
    while true do
      local name, typ = vim.uv.fs_scandir_next(handle)
      if not name then
        break
      end
      if typ == "directory" and not SKIP_DIRS[name] and name:sub(1, 1) ~= "." then
        walk(dir .. "/" .. name, depth + 1)
      end
    end
  end

  walk(root, 0)
  return results
end

---@param root string
---@return { path: string, kind: string }[]
local function find_xcode_under(root)
  root = normalize(root)
  local results = {}

  local function walk(dir, depth)
    if depth > MAX_SCAN_DEPTH then
      return
    end
    local handle = vim.uv.fs_scandir(dir)
    if not handle then
      return
    end
    while true do
      local name, typ = vim.uv.fs_scandir_next(handle)
      if not name then
        break
      end
      if typ == "directory" then
        if name:match("%.xcworkspace$") then
          table.insert(results, { path = normalize(dir .. "/" .. name), kind = "workspace" })
        elseif name:match("%.xcodeproj$") then
          table.insert(results, { path = normalize(dir .. "/" .. name), kind = "project" })
        elseif not SKIP_DIRS[name] and name:sub(1, 1) ~= "." then
          walk(dir .. "/" .. name, depth + 1)
        end
      elseif name == "Package.swift" then
        table.insert(results, { path = normalize(dir), kind = "spm" })
      end
    end
  end

  walk(root, 0)
  return results
end

---@param root string
---@return { path: string, dir: string, kind: string }[]
local function find_dotnet_under(root)
  root = normalize(root)
  local results = {}

  local function walk(dir, depth)
    if depth > MAX_SCAN_DEPTH then
      return
    end
    local handle = vim.uv.fs_scandir(dir)
    if not handle then
      return
    end
    while true do
      local name, typ = vim.uv.fs_scandir_next(handle)
      if not name then
        break
      end
      if typ == "directory" then
        if not SKIP_DIRS[name] and name:sub(1, 1) ~= "." then
          walk(dir .. "/" .. name, depth + 1)
        end
      elseif typ == "file" then
        if name:match("%.sln$") then
          table.insert(results, {
            path = normalize(dir .. "/" .. name),
            dir = normalize(dir),
            kind = "sln",
            name = name,
          })
        elseif name:match("%.csproj$") then
          table.insert(results, {
            path = normalize(dir .. "/" .. name),
            dir = normalize(dir),
            kind = "csproj",
            name = name,
          })
        elseif name:match("%.fsproj$") then
          table.insert(results, {
            path = normalize(dir .. "/" .. name),
            dir = normalize(dir),
            kind = "fsproj",
            name = name,
          })
        end
      end
    end
  end

  walk(root, 0)
  return results
end

---@param pom_dir string
---@param gradle_roots string[]
---@return boolean
local function pom_inside_gradle(pom_dir, gradle_roots)
  pom_dir = normalize(pom_dir)
  for _, g in ipairs(gradle_roots) do
    g = normalize(g)
    if pom_dir == g or pom_dir:sub(1, #g + 1) == g .. "/" then
      local has_gradle_build = vim.fn.filereadable(pom_dir .. "/build.gradle") == 1
        or vim.fn.filereadable(pom_dir .. "/build.gradle.kts") == 1
        or vim.fn.filereadable(pom_dir .. "/gradlew") == 1
        or vim.fn.filereadable(pom_dir .. "/settings.gradle") == 1
        or vim.fn.filereadable(pom_dir .. "/settings.gradle.kts") == 1
      if has_gradle_build then
        return true
      end
    end
  end
  return false
end

---@param path string package/module root
---@param anchor string buffer/cwd dir
---@return boolean true if path is anchor or an ancestor of anchor
local function contains_path(path, anchor)
  path = normalize(path)
  anchor = normalize(anchor)
  return anchor == path or anchor:sub(1, #path + 1) == path .. "/"
end

---@param result table
---@param anchor string
---@return table
local function apply_anchor_context(result, anchor)
  result.anchor = anchor

  local deepest_npm
  for _, pkg in ipairs(result.npm) do
    pkg.containing = contains_path(pkg.dir, anchor)
    if pkg.containing and (not deepest_npm or #pkg.dir > #deepest_npm) then
      deepest_npm = pkg.dir
    end
  end
  for _, pkg in ipairs(result.npm) do
    pkg.primary = deepest_npm ~= nil and pkg.dir == deepest_npm
    pkg.proximate = pkg.primary
  end
  table.sort(result.npm, function(a, b)
    if a.primary ~= b.primary then
      return a.primary
    end
    if a.containing ~= b.containing then
      return a.containing
    end
    if a.containing and b.containing and #a.dir ~= #b.dir then
      return #a.dir > #b.dir
    end
    return a.label < b.label
  end)

  for _, gradle in ipairs(result.gradle) do
    gradle.containing = contains_path(gradle.root, anchor)
    gradle.proximate = gradle.containing
    gradle.current_module = M.module_for_path(gradle.modules, anchor, gradle.root)
  end
  table.sort(result.gradle, function(a, b)
    if a.proximate ~= b.proximate then
      return a.proximate
    end
    return a.label < b.label
  end)

  for _, maven in ipairs(result.maven) do
    maven.containing = contains_path(maven.dir, anchor)
    maven.proximate = maven.containing
  end
  table.sort(result.maven, function(a, b)
    if a.proximate ~= b.proximate then
      return a.proximate
    end
    if a.proximate and b.proximate and #a.dir ~= #b.dir then
      return #a.dir > #b.dir
    end
    return a.label < b.label
  end)

  for _, xcode in ipairs(result.xcode) do
    xcode.containing = contains_path(xcode.path, anchor)
    xcode.proximate = xcode.containing
  end

  local primary_path
  local primary_score = -1
  for _, project in ipairs(result.dotnet) do
    project.containing = contains_path(project.dir, anchor)
    project.primary = false
    project.proximate = false
    if project.containing then
      local score = #project.dir * 10 + (project.kind == "sln" and 0 or 1)
      if score > primary_score then
        primary_score = score
        primary_path = project.path
      end
    end
  end
  for _, project in ipairs(result.dotnet) do
    project.primary = primary_path ~= nil and project.path == primary_path
    project.proximate = project.primary
  end
  table.sort(result.dotnet, function(a, b)
    if a.primary ~= b.primary then
      return a.primary
    end
    if a.containing ~= b.containing then
      return a.containing
    end
    return a.label < b.label
  end)
  return result
end

---@param anchor string|nil
---@return table
function M.discover_workspaces(anchor)
  anchor = normalize(anchor or vim.fn.getcwd())
  local git = M.git_root(anchor)
  setup_cache_invalidation()
  discovery_cache[git] = discovery_cache[git] or {}
  if discovery_cache[git][anchor] then
    cache_stats.hits = cache_stats.hits + 1
    return discovery_cache[git][anchor]
  end
  if discovery_cache[git].__structure then
    cache_stats.hits = cache_stats.hits + 1
    local contextual = apply_anchor_context(vim.deepcopy(discovery_cache[git].__structure), anchor)
    discovery_cache[git][anchor] = contextual
    return contextual
  end
  cache_stats.misses = cache_stats.misses + 1

  local npm_pkgs = {}
  local deepest_npm
  for _, pkg in ipairs(M.find_npm_packages(git)) do
    local dir = vim.fs.dirname(pkg)
    local containing = contains_path(dir, anchor)
    if containing and (not deepest_npm or #dir > #deepest_npm) then
      deepest_npm = dir
    end
    table.insert(npm_pkgs, {
      path = pkg,
      dir = dir,
      label = M.relpath(git, dir),
      manager = M.package_manager(dir),
      containing = containing,
      primary = false,
    })
  end
  for _, pkg in ipairs(npm_pkgs) do
    pkg.primary = deepest_npm ~= nil and pkg.dir == deepest_npm
    -- Back-compat for templates
    pkg.proximate = pkg.primary
  end
  table.sort(npm_pkgs, function(a, b)
    if a.primary ~= b.primary then
      return a.primary
    end
    if a.containing ~= b.containing then
      return a.containing
    end
    if a.containing and b.containing and #a.dir ~= #b.dir then
      return #a.dir > #b.dir
    end
    return a.label < b.label
  end)

  local gradle = {}
  for _, root in ipairs(find_gradle_roots_under(git)) do
    local modules = M.gradle_modules(root)
    local containing = contains_path(root, anchor)
    table.insert(gradle, {
      root = root,
      label = M.relpath(git, root),
      modules = modules,
      current_module = M.module_for_path(modules, anchor, root),
      kmp = M.is_kmp(root),
      android = M.has_android(root),
      jvm = M.has_jvm_target(root),
      containing = containing,
      proximate = containing,
    })
  end
  table.sort(gradle, function(a, b)
    if a.proximate ~= b.proximate then
      return a.proximate
    end
    return a.label < b.label
  end)

  local gradle_roots = vim.tbl_map(function(g)
    return g.root
  end, gradle)

  local maven = {}
  for _, pom in ipairs(find_maven_poms_under(git)) do
    local dir = vim.fs.dirname(pom)
    if not pom_inside_gradle(dir, gradle_roots) then
      local containing = contains_path(dir, anchor)
      table.insert(maven, {
        pom = pom,
        dir = dir,
        label = M.relpath(git, dir),
        containing = containing,
        proximate = containing,
      })
    end
  end
  table.sort(maven, function(a, b)
    if a.proximate ~= b.proximate then
      return a.proximate
    end
    if a.proximate and b.proximate and #a.dir ~= #b.dir then
      return #a.dir > #b.dir
    end
    return a.label < b.label
  end)

  local xcode = find_xcode_under(git)
  for _, x in ipairs(xcode) do
    x.label = M.relpath(git, x.path)
    x.containing = contains_path(x.path, anchor)
    x.proximate = x.containing
  end

  local dotnet = {}
  for _, proj in ipairs(find_dotnet_under(git)) do
    table.insert(dotnet, {
      path = proj.path,
      dir = proj.dir,
      kind = proj.kind,
      name = proj.name,
      label = M.relpath(git, proj.path),
      containing = contains_path(proj.dir, anchor),
      primary = false,
      proximate = false,
    })
  end
  local primary_path
  local primary_score = -1
  for _, proj in ipairs(dotnet) do
    if proj.containing then
      -- Prefer deeper paths; prefer csproj/fsproj over sln at the same depth
      local score = #proj.dir * 10 + (proj.kind == "sln" and 0 or 1)
      if score > primary_score then
        primary_score = score
        primary_path = proj.path
      end
    end
  end
  for _, proj in ipairs(dotnet) do
    proj.primary = primary_path ~= nil and proj.path == primary_path
    proj.proximate = proj.primary
  end
  table.sort(dotnet, function(a, b)
    if a.primary ~= b.primary then
      return a.primary
    end
    if a.containing ~= b.containing then
      return a.containing
    end
    return a.label < b.label
  end)

  local result = {
    git_root = git,
    anchor = anchor,
    npm = npm_pkgs,
    gradle = gradle,
    maven = maven,
    xcode = xcode,
    dotnet = dotnet,
  }
  discovery_cache[git][anchor] = result
  discovery_cache[git].__structure = vim.deepcopy(result)
  return result
end


---@return { hits: integer, misses: integer }
function M._cache_stats()
  return vim.deepcopy(cache_stats)
end

---Nearest package.json directory that contains `dir` (walks up).
---@param dir string
---@return string|nil
function M.nearest_npm_dir(dir)
  dir = normalize(dir)
  local pkg = vim.fs.find("package.json", { upward = true, path = dir, type = "file" })[1]
  if pkg then
    return normalize(vim.fs.dirname(pkg))
  end
  return nil
end

---@param cb fun(serial: string|nil)
function M.pick_android_device(cb)
  if vim.fn.executable("adb") ~= 1 then
    vim.notify("adb not found on PATH", vim.log.levels.WARN, { title = "mobile" })
    return cb(nil)
  end

  vim.system({ "adb", "devices" }, { text = true }, function(obj)
    vim.schedule(function()
      if obj.code ~= 0 then
        vim.notify("adb devices failed", vim.log.levels.ERROR, { title = "mobile" })
        return cb(nil)
      end
      local devices = {}
      for line in (obj.stdout or ""):gmatch("[^\r\n]+") do
        local serial, status = line:match("^(%S+)%s+(%S+)$")
        if serial and serial ~= "List" and status == "device" then
          table.insert(devices, serial)
        end
      end
      if #devices == 0 then
        vim.notify("No Android devices/emulators connected", vim.log.levels.WARN, { title = "mobile" })
        return cb(nil)
      end
      if #devices == 1 then
        vim.g.android_serial = devices[1]
        return cb(devices[1])
      end
      vim.ui.select(devices, { prompt = "Android device" }, function(choice)
        if choice then
          vim.g.android_serial = choice
        end
        cb(choice)
      end)
    end)
  end)
end

---@param cb fun(udid: string|nil)
function M.pick_ios_simulator(cb)
  if vim.fn.executable("xcrun") ~= 1 then
    vim.notify("xcrun not found (Xcode CLT?)", vim.log.levels.WARN, { title = "mobile" })
    return cb(nil)
  end

  vim.system({ "xcrun", "simctl", "list", "devices", "available", "-j" }, { text = true }, function(obj)
    vim.schedule(function()
      if obj.code ~= 0 then
        vim.notify("simctl list failed", vim.log.levels.ERROR, { title = "mobile" })
        return cb(nil)
      end
      local ok, data = pcall(vim.json.decode, obj.stdout or "")
      if not ok or type(data) ~= "table" or type(data.devices) ~= "table" then
        vim.notify("Could not parse simctl JSON", vim.log.levels.ERROR, { title = "mobile" })
        return cb(nil)
      end
      local choices = {}
      for runtime, devices in pairs(data.devices) do
        if type(devices) == "table" then
          for _, d in ipairs(devices) do
            if d.isAvailable ~= false then
              table.insert(choices, {
                label = string.format(
                  "%s (%s) [%s]",
                  d.name or "?",
                  tostring(runtime):gsub(".-%.", ""),
                  d.state or "?"
                ),
                udid = d.udid,
                state = d.state,
              })
            end
          end
        end
      end
      table.sort(choices, function(a, b)
        return a.label < b.label
      end)
      if #choices == 0 then
        vim.notify("No available iOS simulators", vim.log.levels.WARN, { title = "mobile" })
        return cb(nil)
      end
      vim.ui.select(choices, {
        prompt = "iOS simulator",
        format_item = function(item)
          return item.label
        end,
      }, function(choice)
        if not choice then
          return cb(nil)
        end
        vim.g.ios_simulator_udid = choice.udid
        local function open_sim()
          vim.system({ "open", "-a", "Simulator" }, {}, function() end)
          cb(choice.udid)
        end
        if choice.state == "Booted" then
          open_sim()
        else
          vim.system({ "xcrun", "simctl", "boot", choice.udid }, {}, function(boot)
            vim.schedule(function()
              if boot.code ~= 0 and not (boot.stderr or ""):find("current state: Booted", 1, true) then
                vim.notify("Failed to boot simulator", vim.log.levels.ERROR, { title = "mobile" })
                return cb(nil)
              end
              open_sim()
            end)
          end)
        end
      end)
    end)
  end)
end

return M
