local M = {}

local setup_pending = false

local function configured_jar(adapter)
  local jar = adapter and adapter.config and adapter.config.junit_jar
  if type(jar) == "string" then
    return jar
  end
  if jar and type(jar.to_string) == "function" then
    return jar:to_string()
  end
end

function M.launcher_exists(adapter, data_dir)
  local path = configured_jar(adapter)
  if path and vim.fn.filereadable(path) == 1 then
    return true
  end

  local pattern = (data_dir or vim.fn.stdpath("data"))
    .. "/neotest-java/junit-platform-console-standalone-*.jar"
  return #vim.fn.glob(pattern, false, true) > 0
end

--- Start Neotest's checksum-verified installer and resume once its jar exists.
---@param adapter table
---@param on_ready fun()
---@return boolean ready
function M.ensure_launcher(adapter, on_ready)
  if M.launcher_exists(adapter) then
    return true
  end
  if not adapter or type(adapter.install) ~= "function" then
    vim.notify(
      "Java test adapter is unavailable; reload Neotest and try again.",
      vim.log.levels.ERROR,
      { title = "Neotest Java" }
    )
    return false
  end
  if setup_pending then
    return false
  end

  setup_pending = true
  vim.notify(
    "Java tests need the JUnit launcher. Choose download once; the Java suite will resume automatically.",
    vim.log.levels.WARN,
    { title = "Neotest Java" }
  )

  vim.schedule(function()
    adapter.install()
    local attempts = 0
    local function wait_for_install()
      attempts = attempts + 1
      if M.launcher_exists(adapter) then
        setup_pending = false
        on_ready()
      elseif attempts < 480 then
        vim.defer_fn(wait_for_install, 250)
      else
        setup_pending = false
        vim.notify(
          "JUnit launcher setup was not completed. Run :NeotestJava setup when ready.",
          vim.log.levels.INFO,
          { title = "Neotest Java" }
        )
      end
    end
    wait_for_install()
  end)

  return false
end

return M
