-- Hardened wrappers around weilbith/neotest-gradle for modern Gradle + KMP.
-- Upstream uses `gradle properties --property testResultsDir`, which returns
-- `null` on many projects and then crashes collecting from `null/test`.

local lib = require("neotest.lib")
local xml = require("neotest.lib.xml")
local find_project_directory = require("neotest-gradle.hooks.find_project_directory")
local get_package_name = require("neotest-gradle.hooks.shared_utilities").get_package_name
local upstream_results = require("neotest-gradle.hooks.collect_results")

local M = {}

local function gradle_executable(project_directory)
  local wrapper_root = lib.files.match_root_pattern("gradlew")(project_directory)
  if wrapper_root then
    return wrapper_root .. "/gradlew"
  end
  return "gradle"
end

--- Read module build script to pick a runnable test task.
local function detect_test_task(project_directory)
  local build_file
  for _, name in ipairs({ "build.gradle.kts", "build.gradle" }) do
    local path = project_directory .. "/" .. name
    if vim.fn.filereadable(path) == 1 then
      build_file = path
      break
    end
  end
  if not build_file then
    return "test"
  end

  local content = table.concat(vim.fn.readfile(build_file), "\n")
  local is_kmp = content:find("kotlinMultiplatform", 1, true)
    or content:find("androidMultiplatformLibrary", 1, true)
    or content:find("org.jetbrains.kotlin.multiplatform", 1, true)

  if not is_kmp then
    return "test"
  end

  -- Android KMP host unit tests (Linux-friendly)
  if content:find("withHostTest", 1, true) then
    return "testAndroidHostTest"
  end

  -- Desktop / JVM KMP target
  if content:find("jvm(", 1, true) or content:find("jvm {", 1, true) then
    return "jvmTest"
  end

  return "allTests"
end

local function results_dir_for(project_directory, task_name)
  return project_directory .. "/build/test-results/" .. task_name
end

--- Collect XML report directories under build/test-results (non-recursive per dir).
local function list_result_dirs(project_directory, preferred_task)
  local dirs = {}
  local preferred = results_dir_for(project_directory, preferred_task)
  if vim.fn.isdirectory(preferred) == 1 then
    table.insert(dirs, preferred)
  end

  local root = project_directory .. "/build/test-results"
  if vim.fn.isdirectory(root) == 1 then
    for name, typ in vim.fs.dir(root) do
      if typ == "directory" and name ~= "binary" then
        local path = root .. "/" .. name
        if path ~= preferred then
          table.insert(dirs, path)
        end
      end
    end
  end

  return dirs
end

local function parse_xml_dir(directory_path)
  if vim.fn.isdirectory(directory_path) ~= 1 then
    return {}
  end

  local ok, xml_files = pcall(lib.files.find, directory_path, {
    filter_dir = function(file_name)
      return vim.endswith(file_name, ".xml")
    end,
  })
  if not ok or not xml_files then
    return {}
  end

  local reports = {}
  for _, file_path in ipairs(xml_files) do
    local content_ok, content = pcall(lib.files.read, file_path)
    if content_ok and content then
      local parse_ok, parsed = pcall(xml.parse, content)
      if parse_ok and parsed then
        table.insert(reports, parsed)
      end
    end
  end
  return reports
end

local function as_list(value)
  return (type(value) == "table" and #value > 0) and value or { value }
end

local function find_position_for_test_case(tree, test_case_node)
  local attr = test_case_node._attr or {}
  if not attr.name or not attr.classname then
    return nil
  end
  local test_name = attr.name:gsub("%(.*%)$", "")
  local class_name = attr.classname
  local candidate_ids = {
    class_name .. "." .. test_name,
    class_name:gsub("%$", ".") .. "." .. test_name,
  }

  for _, position in tree:iter() do
    if position then
      for _, candidate_id in ipairs(candidate_ids) do
        if position.id == candidate_id then
          return position
        end
      end
    end
  end
  return nil
end

local function parse_error_from_failure_xml(failure_node, position)
  local type_name = (failure_node._attr or {}).type or ""
  local message = ((failure_node._attr or {}).message or ""):gsub(type_name .. ".*\n", "")
  local stack_trace = failure_node[1] or ""
  local package_name = get_package_name(position.path)
  local line_number

  for _, line in ipairs(vim.split(stack_trace, "[\r]?\n")) do
    local pattern = "^.*at.+" .. package_name .. ".*%(.+..+:(%d+)%)$"
    local match = line:match(pattern)
    if match then
      line_number = tonumber(match) - 1
      break
    end
  end

  return { message = message, line = line_number }
end

local function get_namespaces(tree)
  local namespaces = {}
  for _, position in tree:iter() do
    if position.type == "namespace" then
      table.insert(namespaces, position)
    end
  end
  return namespaces
end

local function test_filter_args(tree, position, task_name)
  -- Aggregating KMP tasks like allTests don't accept --tests
  if task_name == "allTests" then
    return {}
  end

  local arguments = {}
  if position.type == "test" or position.type == "namespace" then
    vim.list_extend(arguments, { "--tests", position.id })
  elseif position.type == "file" then
    for _, namespace in ipairs(get_namespaces(tree)) do
      vim.list_extend(arguments, { "--tests", namespace.id })
    end
  end
  return arguments
end

function M.build_spec(arguments)
  local tree = arguments.tree
  local position = tree:data()
  local project_directory = find_project_directory(position.path)
  if not project_directory then
    return nil
  end

  local gradle = gradle_executable(project_directory)
  local task = detect_test_task(project_directory)
  local cmd = { gradle, "--project-dir", project_directory, task }
  vim.list_extend(cmd, test_filter_args(tree, position, task))

  -- Prefer argv table so paths/filters aren't mangled by shell quoting
  return {
    command = cmd,
    cwd = project_directory,
    context = {
      project_directory = project_directory,
      test_task = task,
      -- Keep upstream typo key for compatibility if anything else reads it
      test_resuls_directory = results_dir_for(project_directory, task),
    },
  }
end

function M.results(build_specification, _, tree)
  local context = build_specification.context or {}
  local project_directory = context.project_directory
  local task = context.test_task or "test"

  if not project_directory or project_directory == "" then
    -- Fallback: try upstream only if path looks valid
    local dir = context.test_resuls_directory
    if not dir or dir == "" or dir:match("^null") or vim.fn.isdirectory(dir) ~= 1 then
      return {}
    end
    local ok, res = pcall(upstream_results, build_specification, _, tree)
    return ok and res or {}
  end

  local results = {}
  for _, directory in ipairs(list_result_dirs(project_directory, task)) do
    for _, report in ipairs(parse_xml_dir(directory)) do
      for _, suite in pairs(as_list(report.testsuite)) do
        for _, test_case in pairs(as_list(suite.testcase)) do
          local matched = find_position_for_test_case(tree, test_case)
          if matched then
            local failure = test_case.failure
            local status = failure == nil and "passed" or "failed"
            local short_message = failure and (failure._attr or {}).message or nil
            local error = failure and parse_error_from_failure_xml(failure, matched) or nil
            results[matched.id] = {
              status = status,
              short = short_message,
              errors = error and { error } or {},
            }
          end
        end
      end
    end
  end

  return results
end

--- Apply hardened build_spec + results onto a neotest-gradle adapter instance.
function M.patch(adapter)
  adapter.build_spec = M.build_spec
  adapter.results = M.results
  return adapter
end

return M
