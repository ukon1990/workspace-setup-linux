local M = {}
local suites = {}

local function main_loop()
  if vim.in_fast_event() then
    require("nio").scheduler()
  end
end

local function fail(message)
  vim.schedule(function() vim.notify(message, vim.log.levels.ERROR) end)
  error(message)
end

local function valid(run)
  return not run.cancelled and vim.api.nvim_tabpage_is_valid(run.tab)
end

local function dispose(task)
  if not task:is_running() then
    task:dispose(true)
  end
end

local function release(run)
  if run.blocked then
    release(run.blocked)
    run.blocked = nil
  end
  for _, task in pairs(run.tasks) do dispose(task) end
end

local function stop(run)
  run.cancelled = true
  if run.blocked then stop(run.blocked) end
  for _, task in ipairs(run.tasks) do
    if task:is_running() then
      if task:stop() == false then error("Could not stop test task") end
    end
  end
end

local function stopped(run)
  if not run.done then return false end
  if run.blocked and not stopped(run.blocked) then return false end
  for job in pairs(run.jobs) do
    if vim.fn.jobwait({ job }, 0)[1] == -1 then return false end
  end
  return true
end

local function strategy(run, previous)
  return function(spec)
    local nio = require("nio")
    main_loop()
    if not valid(run) then
      return nil
    end
    local index = #run.tasks + 1
    local output = vim.fn.tempname()
    local finished = nio.control.event()
    local code
    local metadata = {
      tab = run.tab,
      key = run.key .. ":" .. index,
      label = require("config.neotest_discovery").runner_tab_label(run.path),
      valid = function() return valid(run) end,
    }
    local task = require("overseer").new_task({
      name = metadata.label,
      cmd = spec.command,
      cwd = spec.cwd,
      env = spec.env,
      strategy = { "jobstart", use_terminal = true },
      ephemeral = true,
      metadata = { neotest_runner = metadata },
      components = {
        { "on_output_write_file", filename = output },
        "default_neotest",
      },
    })
    task:remove_component("on_complete_dispose")
    run.tasks[index] = task
    task:subscribe("on_complete", function(_, status)
      code = task.exit_code or (status == "SUCCESS" and 0 or 1)
      finished.set()
    end)
    task:subscribe("on_dispose", function()
      code = code or 1
      finished.set()
    end)
    if task:start() == false then fail("Could not start test task") end
    -- Cancellation completes immediately and suppresses Overseer's on_exit.
    -- Retain the jobstart handle, including across a manual Neotest stop.
    local job = task.strategy.job_id
    if job then
      run.jobs[job] = true
    elseif task:is_running() then
      task:stop()
      fail("Overseer jobstart did not expose a process handle")
    end
    -- The previous invocation has finished parsing its output before we get here.
    -- Publish the replacement before disposal removes the old terminal buffer.
    local buf = task:get_bufnr()
    if buf then
      require("config.tool_panel").replace_output(metadata.key, buf, {
        tab = run.tab,
        label = metadata.label,
      })
    end
    if previous and previous.tasks[index] then
      dispose(previous.tasks[index])
      previous.tasks[index] = nil
    end
    return {
      is_complete = function() return finished.is_set() end,
      output = function() return output end,
      result = function()
        finished.wait()
        main_loop()
        return code
      end,
      stop = function()
        main_loop()
        if task:is_running() then task:stop() end
      end,
      attach = function()
        main_loop()
        local bufnr = task:get_bufnr()
        if bufnr and valid(run) then
          require("config.tool_panel").replace_output(metadata.key, bufnr, { tab = run.tab })
        end
      end,
    }
  end
end

function M.install(neotest, client)
  if M.installed then return end
  M.installed = true
  local original = neotest.run.run
  local last
  local sequence = 0
  local function run(args)
    args = type(args) == "string" and { args } or vim.deepcopy(args or {})
    local tab = vim.api.nvim_get_current_tabpage()
    sequence = sequence + 1
    local request = sequence
    last = nil
    if (not args[1] and not args.suite) or (args.strategy and args.strategy ~= "overseer") then
      return original(args)
    end
    return require("nio").run(function()
      local tree, adapter = client:get_position(args[1], args)
      main_loop()
      if not vim.api.nvim_tabpage_is_valid(tab) then return end
      if not tree then return original(args) end
      if args.suite then tree = tree:root() end
      if tree:data().type ~= "dir" then return original(args) end
      local path = vim.fs.normalize(vim.fn.fnamemodify(tree:data().path, ":p"))
      if path ~= "/" then path = path:gsub("/+$", "") end
      local key = vim.json.encode({ tab, adapter, path })
      local previous = suites[key]
      if previous and previous.request > request then return end
      local current = { tab = tab, key = key, path = path, tasks = {}, jobs = {}, done = false, request = request }
      suites[key] = current
      local success, err = pcall(function()
        if previous then
          stop(previous)
          -- Coalesce bursts before allocating another terminal/process.
          require("nio").sleep(1)
          main_loop()
          local started = vim.uv.now()
          while not stopped(previous) do
            if vim.uv.now() - started > 10000 then
              error("Timed out stopping previous test suite")
            end
            require("nio").sleep(10)
            main_loop()
          end
          for _, task in pairs(previous.tasks) do
            if task:is_running() then error("Previous test process did not stop") end
          end
        end
        if not valid(current) then return end
        args[1], args.adapter = tree:data().id, adapter
        if request == sequence then last = vim.deepcopy(args) end
        args.strategy = strategy(current, previous)
        original(args)
      end)
      main_loop()
      current.done = true
      if previous then
        if stopped(previous) then
          release(previous)
        end
      end
      if not vim.api.nvim_tabpage_is_valid(current.tab) then
        release(current)
      end
      if not success then
        current.cancelled = true
        current.blocked = previous and not stopped(previous) and previous or nil
        local stopped_ok, stop_err = pcall(stop, current)
        if not stopped_ok then err = tostring(err) .. "; " .. tostring(stop_err) end
        vim.schedule(function()
          vim.notify("Test suite restart failed: " .. tostring(err), vim.log.levels.ERROR)
        end)
      end
    end)
  end
  neotest.run.run = run
  local original_last = neotest.run.run_last
  neotest.run.run_last = function(args)
    if not last then return original_last(args) end
    return run(vim.tbl_extend("force", last, args or {}))
  end
  vim.api.nvim_create_autocmd("TabClosed", {
    group = vim.api.nvim_create_augroup("neotest_runner", { clear = true }),
    callback = function()
      for key, current in pairs(suites) do
        if not vim.api.nvim_tabpage_is_valid(current.tab) then
          stop(current)
          if current.done then
            release(current)
          end
          suites[key] = nil
        end
      end
    end,
  })
end

return M
