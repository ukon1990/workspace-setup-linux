-- Java LSP via nvim-jdtls (do not vim.lsp.enable("jdtls") — Mason excludes it)

local ok, jdtls = pcall(require, "jdtls")
if not ok then
  return
end

local function java_home_for(version)
  local handle = io.popen(string.format("/usr/libexec/java_home -v %s 2>/dev/null", version))
  if not handle then
    return nil
  end
  local path = handle:read("*l")
  handle:close()
  if path and path ~= "" then
    return path
  end
  return nil
end

local root_markers = { "gradlew", "mvnw", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", ".git" }
local root_dir = vim.fs.root(0, root_markers)
if not root_dir then
  root_dir = vim.fn.getcwd()
end

local project_name = vim.fn.fnamemodify(root_dir, ":p:h:t")
local workspace_dir = vim.fn.stdpath("cache") .. "/jdtls-workspace/" .. project_name

local mason_jdtls = vim.fn.stdpath("data") .. "/mason/bin/jdtls"
local cmd = { "jdtls", "-data", workspace_dir }
if vim.fn.executable(mason_jdtls) == 1 then
  cmd[1] = mason_jdtls
elseif vim.fn.executable("jdtls") ~= 1 then
  vim.notify("jdtls not found. Open :Mason and install jdtls.", vim.log.levels.WARN)
  return
end

local runtimes = {}
local runtime_map = {
  { name = "JavaSE-21", version = "21" },
  { name = "JavaSE-25", version = "25" },
  { name = "JavaSE-26", version = "26" },
}
for _, rt in ipairs(runtime_map) do
  local path = java_home_for(rt.version)
  if path then
    table.insert(runtimes, { name = rt.name, path = path })
  end
end

local config = {
  name = "jdtls",
  cmd = cmd,
  root_dir = root_dir,
  settings = {
    java = {
      eclipse = { downloadSources = true },
      configuration = {
        updateBuildConfiguration = "interactive",
        runtimes = runtimes,
      },
      maven = { downloadSources = true },
      implementationsCodeLens = { enabled = true },
      referencesCodeLens = { enabled = true },
      references = { includeDecompiledSources = true },
      format = { enabled = true },
    },
  },
  init_options = {
    bundles = {},
  },
  on_attach = function(_, bufnr)
    local function map(mode, lhs, rhs, desc)
      vim.keymap.set(mode, lhs, rhs, { buffer = bufnr, desc = desc })
    end

    map("n", "<leader>jo", jdtls.organize_imports, "Organize imports")
    map("n", "<leader>jv", jdtls.extract_variable, "Extract variable")
    map("v", "<leader>jv", function()
      jdtls.extract_variable(true)
    end, "Extract variable")
    map("n", "<leader>jc", jdtls.extract_constant, "Extract constant")
    map("v", "<leader>jc", function()
      jdtls.extract_constant(true)
    end, "Extract constant")
    map("v", "<leader>jm", function()
      jdtls.extract_method(true)
    end, "Extract method")
  end,
}

jdtls.start_or_attach(config)
