local function eq(actual, expected, message)
  if not vim.deep_equal(actual, expected) then
    error((message or "values differ") .. ": expected " .. vim.inspect(expected) .. ", got " .. vim.inspect(actual))
  end
end

local function ok(value, message)
  if not value then
    error(message or "assertion failed")
  end
end

-- Reproduce the real integration: winbuf schedules a deferred winbar refresh
-- whenever the dock switches between neotest and Overseer buffers.
require("lazy").load({ plugins = { "winbuf.nvim" } })

local panel = require("config.tool_panel")
local original_win = vim.api.nvim_get_current_win()

local build_buf = vim.api.nvim_create_buf(false, true)
vim.api.nvim_buf_set_name(build_buf, "gradle build")
local build_win = panel.show_buf(build_buf, { focus = false })
eq(vim.api.nvim_get_current_win(), original_win, "opening output changed focus")

local test_buf = vim.api.nvim_create_buf(false, true)
vim.api.nvim_buf_set_name(test_buf, "Neotest Output Panel")
vim.bo[test_buf].filetype = "neotest-output-panel"
local test_win = panel.show_buf(test_buf, { focus = false })
vim.wait(50, function()
  return false
end, 10)
eq(test_win, build_win, "outputs did not reuse the dock")
eq(#panel._state().history, 2, "output history was not retained")
ok(panel.winbar(test_win):find("gradle build", 1, true), "build tab missing")
ok(panel.winbar(test_win):find("tests", 1, true), "test tab missing")

panel.show_buf(build_buf, { focus = false })
vim.wait(50, function()
  return false
end, 10)
local dock_winbar = vim.api.nvim_get_option_value("winbar", { win = build_win })
ok(dock_winbar:find("config.tool_panel", 1, true), "winbuf replaced the output dock winbar")
ok(panel.winbar(build_win):find("tests", 1, true), "test tab disappeared after selecting build output")

vim.cmd("tabnew")
local second_tab = vim.api.nvim_get_current_tabpage()
local second_buf = vim.api.nvim_create_buf(false, true)
vim.api.nvim_buf_set_name(second_buf, "second tab task")
local second_win = panel.show_buf(second_buf, { focus = false })
ok(second_win ~= build_win, "dock leaked across tabpages")
eq(#panel._state().history, 1, "tabpage output history leaked")
require("winbuf").refresh()
ok(
  vim.api.nvim_get_option_value("winbar", { win = build_win }):find("config.tool_panel", 1, true),
  "inactive tabpage dock lost its winbar"
)
vim.cmd("tabclose")
ok(not vim.api.nvim_tabpage_is_valid(second_tab), "test tabpage did not close")

panel.close()
local replacement = panel.ensure_win({ focus = false })
ok(vim.api.nvim_win_is_valid(replacement), "dock did not recover after close")
panel.close()

local sidebar_a = panel.ensure_sidebar("tasks", { focus = false })
local sidebar_b = panel.ensure_sidebar("tests", { focus = false })
ok(sidebar_a ~= sidebar_b, "activity rail switch reused a stale plugin window")
eq(panel._state().sidebar_kind, "tests", "activity rail kind was not updated")
vim.api.nvim_win_close(sidebar_b, true)

local summary_buf = vim.api.nvim_create_buf(false, true)
vim.api.nvim_win_set_buf(0, summary_buf)
vim.bo[summary_buf].filetype = "neotest-summary"
eq(vim.wo.wrap, false, "test summary wrapping is enabled")
ok(vim.wo.listchars:find("extends:…", 1, true), "test summary ellipsis marker missing")

local errors = require("config.task_errors")
local fixtures = {
  gradle = "e: file:///tmp/Foo.kt:12:7 Unresolved reference",
  maven = "[ERROR] /tmp/Foo.java:[8,3] cannot find symbol",
  npm = "src/app.ts(4,9): error TS2322: bad",
  dotnet = "Program.cs(10,5): error CS1002: ; expected [app.csproj]",
  xcode = "/tmp/App.swift:14:2: error: cannot find thing",
}
for kind, line in pairs(fixtures) do
  local parsed = vim.fn.getqflist({ lines = { line }, efm = errors.errorformat(kind) }).items
  eq(#parsed, 1, kind .. " fixture count")
  eq(parsed[1].valid, 1, kind .. " fixture was not parsed")
end

require("lazy").load({ plugins = { "overseer.nvim" } })
local overseer = require("overseer")
local task = overseer.new_task({
  cmd = { "sh", "-c", "printf 'src/demo.ts(4,9): error TS2322: bad\\n'; exit 1" },
  components = errors.components("npm"),
})
task:start()
ok(vim.wait(3000, function()
  return task:is_complete()
end, 20), "fixture task timed out")
local task_qf = vim.fn.getqflist({ context = 0, items = 0 })
eq(task_qf.context, task.id, "task quickfix context")
eq(#task_qf.items, 1, "task quickfix parsed item count")

local tools = require("config.project_tools")
tools.clear_cache()
local before = tools._cache_stats()
tools.discover_workspaces(vim.uv.cwd())
tools.discover_workspaces(vim.uv.cwd())
tools.discover_workspaces(vim.uv.cwd() .. "/stow")
local after = tools._cache_stats()
eq(after.misses, before.misses + 1, "project discovery cache miss count")
eq(after.hits, before.hits + 2, "project discovery cache hit count")

print("nvim headless tests: ok")
