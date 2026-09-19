-- Maven test adapter for Java + Kotlin (Surefire / Failsafe via mvnw).
-- Reuses neotest-gradle Treesitter discovery; runs `./mvnw test` / `verify`.

local lib = require("neotest.lib")
local xml = require("neotest.lib.xml")
local get_package_name = require("neotest-gradle.hooks.shared_utilities").get_package_name
local discover_positions = require("neotest-gradle.hooks.discover_positions")

local M = {}

local TEST_FILE_PATTERNS = {
  "Test%.kt$",
  "Tests%.kt$",
  "IT%.kt$",
  "Spec%.kt$",
  "Test%.java$",
  "Tests%.java$",
  "IT%.java$",
  "Spec%.java$",
}

local function maven_executable(project_directory)
  local wrapper = project_directory .. "/mvnw"
  if vim.fn.executable(wrapper) == 1 or vim.fn.filereadable(wrapper) == 1 then
    return wrapper
  end
  return "mvn"
end

local function find_maven_project(path)
  local dir = vim.fn.isdirectory(path) == 1 and path or vim.fs.dirname(path)
  return lib.files.match_root_pattern("pom.xml", "mvnw", "mvnw.cmd")(dir)
end

local function add_unique(values, seen, value)
  if value and not seen[value] then
    seen[value] = true
    table.insert(values, value)
  end
end

local function as_list(value)
  return (type(value) == "table" and #value > 0) and value or { value }
end

local function class_and_method(position_id)
  local class_name, method = position_id:match("^(.*)%.([^%.]+)$")
  if not class_name or class_name == "" then
    return position_id, nil
  end
  -- Namespaces are FQCN; tests are FQCN.method
  return class_name, method
end

local function surefire_filter(tree, position)
  if position.type == "dir" then
    return nil
  end

  local filters = {}
  local seen = {}

  local function add_position(pos)
    if pos.type == "namespace" then
      add_unique(filters, seen, pos.id)
    elseif pos.type == "test" then
      local class_name, method = class_and_method(pos.id)
      if method then
        add_unique(filters, seen, class_name .. "#" .. method)
      else
        add_unique(filters, seen, pos.id)
      end
    elseif pos.type == "file" then
      for _, node in tree:iter() do
        if node.type == "namespace" and node.path == pos.path then
          add_unique(filters, seen, node.id)
        end
      end
    end
  end

  add_position(position)
  if #filters == 0 then
    return nil
  end
  return table.concat(filters, ",")
end

local function report_dirs(project_directory)
  return {
    project_directory .. "/target/surefire-reports",
    project_directory .. "/target/failsafe-reports",
  }
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

local function candidate_ids(test_case_node)
  local attr = test_case_node._attr or {}
  if not attr.name or not attr.classname then
    return {}
  end
  local test_name = attr.name:gsub("%b()$", ""):gsub("%b[]$", "")
  local class_name = attr.classname
  return {
    class_name .. "." .. test_name,
    class_name:gsub("%$", ".") .. "." .. test_name,
  }
end

local function index_positions(tree)
  local positions = {}
  for _, position in tree:iter() do
    if position and position.id then
      positions[position.id] = position
    end
  end
  return positions
end

local function find_position(positions, test_case_node)
  for _, candidate in ipairs(candidate_ids(test_case_node)) do
    if positions[candidate] then
      return positions[candidate]
    end
  end
end

local function parse_error(failure_node, position)
  local type_name = (failure_node._attr or {}).type or ""
  local message = ((failure_node._attr or {}).message or ""):gsub(type_name .. ".*\n", "")
  local stack_trace = failure_node[1] or ""
  local package_name = get_package_name(position.path)
  local line_number
  for _, line in ipairs(vim.split(stack_trace, "[\r]?\n")) do
    local match = line:match("^.*at.+" .. package_name .. ".*%(.+..+:(%d+)%)$")
    if match then
      line_number = tonumber(match) - 1
      break
    end
  end
  return { message = message, line = line_number }
end

function M.create()
  ---@type neotest.Adapter
  local adapter = {
    name = "neotest-maven",
    root = function(dir)
      return find_maven_project(dir)
    end,
    filter_dir = function(name)
      return name ~= "target"
        and name ~= "node_modules"
        and name ~= "build"
        and name ~= ".git"
        and name ~= ".mvn"
    end,
    is_test_file = function(file_path)
      if require("config.neotest_discovery").nearest_jvm_build(file_path) ~= "maven" then
        return false
      end
      for _, pattern in ipairs(TEST_FILE_PATTERNS) do
        if file_path:match(pattern) then
          return true
        end
      end
      return false
    end,
    discover_positions = discover_positions,
    build_spec = function(args)
      local tree = args.tree
      local position = tree:data()
      local project_directory = find_maven_project(position.path)
      if not project_directory then
        return nil
      end

      local mvn = maven_executable(project_directory)
      local filter = surefire_filter(tree, position)
      local goal = (position.name and position.name:match("IT$")) and "verify" or "test"
      local cmd = { mvn, "-f", project_directory .. "/pom.xml", goal }
      if filter then
        vim.list_extend(cmd, { "-Dtest=" .. filter })
        if goal == "verify" then
          vim.list_extend(cmd, { "-Dit.test=" .. filter })
        end
      end

      return {
        command = cmd,
        cwd = project_directory,
        context = {
          project_directory = project_directory,
          report_dirs = report_dirs(project_directory),
        },
      }
    end,
    results = function(spec, result, tree)
      local context = spec.context or {}
      local positions = index_positions(tree)
      local results = {}

      for _, directory in ipairs(context.report_dirs or {}) do
        for _, report in ipairs(parse_xml_dir(directory)) do
          for _, suite in pairs(as_list(report.testsuite)) do
            for _, test_case in pairs(as_list(suite.testcase)) do
              local matched = find_position(positions, test_case)
              if matched then
                local failure = test_case.failure or test_case.error
                local status = failure == nil and "passed" or "failed"
                local short = failure and (failure._attr or {}).message or nil
                local error = failure and parse_error(failure, matched) or nil
                results[matched.id] = {
                  status = status,
                  short = short,
                  errors = error and { error } or {},
                }
              end
            end
          end
        end
      end

      if next(results) or not result or result.code == 0 then
        for _, position in tree:iter() do
          if position.type == "test" and not results[position.id] then
            results[position.id] = { status = "skipped", errors = {} }
          end
        end
      else
        results[tree:data().id] = {
          status = "failed",
          short = "Maven exited before producing test results",
          errors = {},
        }
      end

      return results
    end,
  }

  return adapter
end

M._surefire_filter = surefire_filter
M._class_and_method = class_and_method

return M
