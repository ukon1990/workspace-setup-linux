-- Real Neotest/Overseer lifecycle fixture; no installed plugin source is read.
local function check(value, message)
  assert(value, message)
end
local function wait(predicate, message)
  check(vim.wait(10000, predicate, 10), message)
end
local function resume_in_fast_event()
  local event = require("nio").control.event()
  local timer = assert(vim.uv.new_timer())
  timer:start(1, 0, function()
    timer:stop()
    timer:close()
    event.set()
  end)
  event.wait()
  check(vim.in_fast_event(), "fixture did not resume from a fast event")
end
require("lazy").load({ plugins = { "neotest" } })
local nt = require("neotest")
local panel = require("config.tool_panel")
local overseer = require("overseer")
local root = vim.fn.tempname()
for _, dir in ipairs({ "suite-A", "suite-B", "other/suite-A" }) do
  vim.fn.mkdir(root .. "/" .. dir, "p")
  vim.fn.writefile({ "test" }, root .. "/" .. dir .. "/test.fixture")
end
local serial, completed = 0, 0
local duration, exit_code, spec_count = "0.02", 0, 1
local created, results = {}, {}
local built = {}
local must_exit
local function adapter(name)
  return {
    name = name,
    root = function() return root end,
    filter_dir = function() return true end,
    is_test_file = function(path) return path:match("/test%.fixture$") ~= nil end,
    discover_positions = function(path)
      return require("neotest.types").Tree.from_list({
        { id = path, path = path, name = "file", type = "file" },
        { { id = path .. "::test", path = path, name = "test", type = "test", range = { 0, 0, 0, 1 } } },
      }, function(p) return p.id end)
    end,
    build_spec = function(args)
      resume_in_fast_event()
      built[#built + 1] = args.tree:data()
      serial = serial + 1
      local specs = {}
      for i = 1, spec_count do
        specs[i] = {
          command = { "sh", "-c", ("printf 'run-%d-spec-%d\\n'; sleep %s; exit %d"):format(serial, i, duration, exit_code) },
          cwd = root,
          context = { tree = args.tree, serial = serial },
        }
      end
      return specs
    end,
    results = function(spec, result)
      resume_in_fast_event()
      completed = completed + 1
      results[#results + 1] = result
      local parsed = {}
      for _, position in spec.context.tree:iter() do
        if position.type == "test" then
          parsed[position.id] = { status = result.code == 0 and "passed" or "failed", output = result.output }
        end
      end
      return parsed
    end,
  }
end
local client
local published = {}
nt.setup({
  adapters = { adapter("fixture-one"), adapter("fixture-two") },
  default_strategy = "overseer",
  strategies = { overseer = { components = { "default_neotest" } } },
  consumers = {
    overseer = require("neotest.consumers.overseer"),
    fixture = function(c)
      client = c
      c.listeners.results = function(adapter_id, parsed, partial)
        if not partial then
          published[adapter_id] = vim.tbl_extend("force", published[adapter_id] or {}, parsed)
        end
      end
      return {}
    end,
  },
  output = { open_on_run = false },
  output_panel = { enabled = false },
  summary = { mappings = { run = "r" } },
  quickfix = { open = false },
})
local runner = require("config.neotest_runner")
check(runner.installed, "normal plugin setup did not install suite ownership")
runner.installed = nil
runner.install(nt, {
  get_position = function(_, ...)
    local tree, adapter_id = client:get_position(...)
    resume_in_fast_event()
    return tree, adapter_id
  end,
})
local original_new = overseer.new_task
overseer.new_task = function(opts)
  if must_exit then check(must_exit(), "replacement started before old process exited") end
  local task = original_new(opts)
  if opts.metadata and opts.metadata.neotest_runner then created[#created + 1] = task end
  return task
end
local id = "fixture-one:" .. root
local a, b = root .. "/suite-A", root .. "/suite-B"
local function run(path, adapter_id)
  nt.run.run({ path, adapter = adapter_id or id })
end
local function finish(path, adapter_id)
  local before = completed
  run(path, adapter_id)
  wait(function() return completed > before end, "suite did not complete")
  vim.wait(30, function() return false end)
  return created[#created]
end
vim.cmd.edit(root .. "/suite-A/test.fixture")
-- Discovery runs through the public API, just as a first user invocation does.
finish(a)
local owner = vim.api.nvim_get_current_tabpage()
local editor = vim.api.nvim_get_current_win()
local initial = #panel._state().history
local first = created[#created]
local first_buf = first:get_bufnr()
local second = finish(a)
check(#panel._state().history == initial, "folder rerun accumulated slots")
check(not vim.api.nvim_buf_is_valid(first_buf), "old terminal leaked")
check(vim.api.nvim_get_current_win() == editor, "run stole focus")
check(table.concat(vim.fn.readfile(results[#results].output), "\n"):find("run%-2%-spec%-1"), "output was not replaced")
local terminal_output = table.concat(vim.api.nvim_buf_get_lines(second:get_bufnr(), 0, -1, false), "\n")
check(terminal_output:find("run-2-spec-1", 1, true), "replacement terminal is missing current output")
check(not terminal_output:find("run-1-spec-1", 1, true), "replacement terminal retained previous output")

-- Exercise the actual Summary mapping, rather than substituting a key handler.
nt.summary.open({ enter = true })
vim.wait(100, function() return false end)
local summary_buf
for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
  local buf = vim.api.nvim_win_get_buf(win)
  if vim.bo[buf].filetype == "neotest-summary" then
    summary_buf = buf
    vim.api.nvim_set_current_win(win)
    break
  end
end
check(summary_buf, "Summary window did not open")
local function summary_run()
  local lines = vim.api.nvim_buf_get_lines(summary_buf, 0, -1, false)
  local row
  local matching_adapter = false
  for i, line in ipairs(lines) do
    if line:find("fixture%-one") then matching_adapter = true end
    if line:find("fixture%-two") then matching_adapter = false end
    if matching_adapter and line:find("suite-A", 1, true) then row = i end
  end
  check(row, "Summary folder row missing: " .. table.concat(lines, "\n"))
  vim.api.nvim_win_set_cursor(0, { row, 0 })
  for _, map in ipairs(vim.api.nvim_buf_get_keymap(summary_buf, "n")) do
    if map.lhs == "r" then
      check(type(map.callback) == "function", "Summary r callback missing")
      map.callback()
      return
    end
  end
  error("Summary r mapping missing")
end
for _ = 1, 2 do
  local before = completed
  local focused = vim.api.nvim_get_current_win()
  summary_run()
  wait(function() return completed > before end, "Summary run did not finish")
  check(vim.api.nvim_get_current_win() == focused, "Summary run stole focus")
end
check(#panel._state().history == initial, "Summary r accumulated slots: " .. vim.inspect(vim.tbl_map(function(task)
  return task.metadata.neotest_runner
end, created)))
vim.api.nvim_set_current_win(editor)
local b_task = finish(b)
local b_buf = b_task:get_bufnr()
local b_text = vim.api.nvim_buf_get_lines(b_buf, 0, -1, false)
finish(a)
check(#panel._state().history == initial + 1, "A/B/A did not retain two slots")
check(vim.api.nvim_buf_is_valid(b_buf), "A rerun removed B output")
check(vim.deep_equal(b_text, vim.api.nvim_buf_get_lines(b_buf, 0, -1, false)), "A rerun modified B output")
finish(root .. "/other/suite-A")
check(#panel._state().history == initial + 2, "same-basename folders collided")
finish(a, "fixture-two:" .. root)
check(#panel._state().history == initial + 3, "full adapter identities collided")

duration = "2"
local before_tasks = #created
run(a)
wait(function() return #created > before_tasks and created[#created]:is_running() end, "active suite did not start")
local active = created[#created]
local active_slot
for i, buf in ipairs(panel._state().history) do
  if buf == active:get_bufnr() then active_slot = i end
end
local old_output
local old_job = active.strategy.job_id
must_exit = function() return vim.fn.jobwait({ old_job }, 0)[1] ~= -1 end
active:subscribe("on_complete", function() old_output = true end)
duration = "0.02"
local before_results = completed
run(a)
run(a)
run(a)
wait(function() return completed >= before_results + 2 end, "rapid stop/restart did not finish")
check(old_output and must_exit() and not active:is_running(), "old process still running")
check(#created == before_tasks + 2, ("rapid reruns started superseded processes: before %d after %d"):format(before_tasks, #created))
check(panel._state().history[active_slot] == created[#created]:get_bufnr(), "rapid reruns moved the suite slot")
must_exit = nil

spec_count = 2
finish(b)
wait(function() return not created[#created]:is_running() end, "multi-spec execution not finished")
check(created[#created].metadata.neotest_runner.key ~= created[#created - 1].metadata.neotest_runner.key, "multi-spec siblings collided")
local extra_spec_buf = created[#created]:get_bufnr()
spec_count = 1
finish(b)
check(not vim.api.nvim_buf_is_valid(extra_spec_buf), "removed execution spec leaked its terminal")
exit_code = 1
finish(a)
check(results[#results].code ~= 0, "failure reported success")
check(published[id][a .. "/test.fixture::test"].status == "failed", "Neotest failure status lost")
exit_code = 0

-- A failed stop must not launch another process or lose ownership of the old one.
duration = "2"
before_tasks = #created
run(a)
wait(function() return #created > before_tasks and created[#created]:is_running() end, "stop-failure fixture did not start")
local refuses_stop = created[#created]
local real_stop = refuses_stop.stop
local real_notify = vim.notify
local stop_error
vim.notify = function(message, level, opts)
  if tostring(message):find("Could not stop test task", 1, true) then stop_error = message
  else real_notify(message, level, opts) end
end
refuses_stop.stop = function() return false end
run(a)
wait(function() return stop_error ~= nil end, "stop failure was not surfaced")
check(#created == before_tasks + 1, "failed stop launched a replacement")
refuses_stop.stop = real_stop
vim.notify = real_notify
duration = "0.02"
finish(a)
check(published[id][a .. "/test.fixture::test"].status == "passed", "replacement success status lost")

-- Switch tabs while the adapter is still building its specs.
duration = "0.1"
before_tasks = #created
run(a)
vim.cmd("tabnew")
local other_tab = vim.api.nvim_get_current_tabpage()
local other_editor = vim.api.nvim_get_current_win()
wait(function() return #created > before_tasks and not created[#created]:is_running() end, "background run did not finish")
check(vim.api.nvim_get_current_win() == other_editor, "delayed output changed focus")
check(#panel._state().history == 0, "delayed output landed in wrong tab")
finish(a)
check(#panel._state().history == 1, "same suite in second tab missing")
check(created[#created].metadata.neotest_runner.tab == other_tab, "origin tab not captured")
local closed_task = created[#created]
vim.cmd("tabclose")
check(vim.api.nvim_get_current_tabpage() == owner, "owner tab changed")
wait(function()
  return not vim.api.nvim_buf_is_valid(closed_task:get_bufnr() or -1)
end, "closed-tab task leaked")

duration = "2"
before_tasks = #created
run(a)
wait(function() return #created > before_tasks and created[#created]:is_running() end, "owner concurrent run did not start")
local owner_task = created[#created]
vim.cmd("tabnew")
before_tasks = #created
run(a)
wait(function() return #created > before_tasks and created[#created]:is_running() end, "second-tab concurrent run did not start")
check(owner_task:is_running(), "second tab stopped the owner's suite")
local closing_task = created[#created]
local closing_job = closing_task.strategy.job_id
vim.cmd("tabclose")
wait(function() return vim.fn.jobwait({ closing_job }, 0)[1] ~= -1 end, "closed tab retained a running process")
check(owner_task:is_running(), "closing another tab stopped the owner's suite")
duration = "0.02"
finish(a)

panel.close()
finish(a)
check(vim.api.nvim_win_is_valid(panel._state().primary_win), "closed dock did not recover")
local removed = created[#created]
vim.api.nvim_buf_delete(removed:get_bufnr(), { force = true })
finish(a)
created[#created]:dispose(true)
finish(a)
check(vim.api.nvim_buf_is_valid(created[#created]:get_bufnr()), "disposed task did not recover")
local before_last = completed
local before_history = #panel._state().history
nt.run.run_last()
wait(function() return completed > before_last end, "Run last did not finish")
check(#panel._state().history == before_history, "Run last accumulated a suite slot")
local live = {}
for _, task in ipairs(created) do
  local buf = task:get_bufnr()
  if buf and vim.api.nvim_buf_is_valid(buf) then
    local key = task.metadata.neotest_runner.key
    check(not live[key], "superseded task/terminal leaked")
    live[key] = true
  end
end
overseer.new_task = original_new
vim.api.nvim_set_current_win(editor)
vim.cmd.edit(a .. "/test.fixture")
local before_nearest = completed
nt.run.run()
wait(function() return completed > before_nearest end, "nearest test did not finish")
check(built[#built].type ~= "dir", "nearest test was widened into a suite")
local nearest_id = built[#built].id
vim.cmd.edit(b .. "/test.fixture")
before_nearest = completed
nt.run.run_last()
wait(function() return completed > before_nearest end, "nearest Run last did not finish")
check(built[#built].id == nearest_id, "Run last changed nearest-test identity")
for _, task in ipairs(created) do
  if task:is_running() then task:stop() end
  task:dispose(true)
end
vim.fn.delete(root, "rf")
print("neotest runner lifecycle checks passed")
