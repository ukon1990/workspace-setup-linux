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

local summary_win = vim.api.nvim_get_current_win()
vim.w[summary_win].tool_panel = true
vim.cmd("leftabove vnew")
local source_win = vim.api.nvim_get_current_win()
local source_buf = vim.api.nvim_get_current_buf()
vim.api.nvim_buf_set_lines(source_buf, 0, -1, false, { "first", "second line" })
vim.bo[source_buf].modified = false
vim.api.nvim_set_current_win(summary_win)
ok(panel.open_in_editor(source_buf, 1, 4), "test jump could not resolve an editor window")
eq(vim.api.nvim_get_current_win(), source_win, "test jump did not focus the editor")
eq(vim.api.nvim_win_get_cursor(source_win), { 2, 4 }, "test jump did not preserve the source position")
vim.api.nvim_win_close(summary_win, true)

local neotest_icons = require("config.neotest_icons")
local private_use_start = 0xE000
local private_use_end = 0xF8FF
for name, icon in pairs(neotest_icons) do
  local variants = type(icon) == "table" and icon or { icon }
  for _, variant in ipairs(variants) do
    ok(type(variant) == "string" and variant ~= "", "neotest icon " .. name .. " is empty")
    eq(vim.fn.strdisplaywidth(variant), 1, "neotest icon " .. name .. " display width")
  end
end
for _, name in ipairs({ "passed", "failed", "running", "skipped", "unknown", "test" }) do
  local codepoint = vim.fn.char2nr(neotest_icons[name])
  ok(
    codepoint < private_use_start or codepoint > private_use_end,
    "neotest icon " .. name .. " uses a private-use codepoint"
  )
end

local java_launcher = require("config.neotest_java")
local java_fixture_dir = vim.fn.tempname()
vim.fn.mkdir(java_fixture_dir, "p")
local java_fixture_jar = java_fixture_dir .. "/junit.jar"
local fake_java_adapter = {
  config = { junit_jar = java_fixture_jar },
}
eq(java_launcher.launcher_exists(fake_java_adapter, java_fixture_dir), false, "missing Java launcher was reported as installed")
vim.fn.writefile({ "fixture" }, java_fixture_jar)
eq(java_launcher.launcher_exists(fake_java_adapter, java_fixture_dir), true, "configured Java launcher was not detected")
vim.fn.delete(java_fixture_dir, "rf")

-- Safe open_term reuse: second open on the same terminal buffer must not throw.
require("lazy").load({ plugins = { "neotest" } })
local neotest_ui = require("neotest.lib").ui
-- Force the patched open_term from plugin config by ensuring neotest config ran.
require("lazy").load({ plugins = { "neotest" } })
local term_buf = vim.api.nvim_create_buf(false, true)
local chan1 = neotest_ui.open_term(term_buf)
ok(type(chan1) == "number", "first open_term did not return a channel")
local chan2 = neotest_ui.open_term(term_buf)
eq(chan2, chan1, "second open_term did not reuse the existing terminal channel")
pcall(vim.fn.chanclose, chan1)
pcall(vim.api.nvim_buf_delete, term_buf, { force = true })

local neotest_discovery = require("config.neotest_discovery")
local jvm_fixture = vim.fn.tempname()
local maven_mod = jvm_fixture .. "/backend"
local gradle_mod = jvm_fixture .. "/app"
local frontend = jvm_fixture .. "/frontend"
vim.fn.mkdir(maven_mod .. "/src/test/java", "p")
vim.fn.mkdir(gradle_mod .. "/src/test/java", "p")
vim.fn.mkdir(frontend, "p")
vim.fn.writefile({ "<project/>" }, maven_mod .. "/pom.xml")
vim.fn.writefile({ "plugins {}" }, gradle_mod .. "/build.gradle.kts")
vim.fn.writefile({ "rootProject.name = 'app'" }, jvm_fixture .. "/settings.gradle.kts")
vim.fn.writefile({
  '{ "devDependencies": { "vitest": "^1.0.0" } }',
}, frontend .. "/package.json")
eq(
  neotest_discovery.nearest_jvm_build(maven_mod .. "/src/test/java/ExampleTest.java"),
  "maven",
  "Maven module claimed by nearest Gradle root"
)
eq(
  neotest_discovery.nearest_jvm_build(gradle_mod .. "/src/test/java/ExampleTest.java"),
  "gradle",
  "Gradle module not detected"
)
eq(neotest_discovery.npm_has_vitest(frontend), true, "Vitest package not detected")
eq(neotest_discovery.npm_has_jest(frontend), false, "Vitest package falsely reported Jest")
local analog_pkg = jvm_fixture .. "/analog-app"
vim.fn.mkdir(analog_pkg, "p")
vim.fn.writefile({
  '{ "devDependencies": { "@analogjs/vitest-angular": "^2.0.0" } }',
}, analog_pkg .. "/package.json")
eq(neotest_discovery.npm_has_vitest(analog_pkg), true, "Analog Vitest package not detected")
eq(neotest_discovery.is_js_test_file(frontend .. "/src/app.spec.ts"), true, "spec.ts not treated as JS test")
eq(neotest_discovery.is_js_test_file(frontend .. "/src/app.ts"), false, "non-test ts treated as JS test")

local nested_lib = frontend .. "/ethereal-ui"
vim.fn.mkdir(nested_lib .. "/src", "p")
vim.fn.writefile({ '{ "name": "ethereal-ui" }' }, nested_lib .. "/package.json")
vim.fn.writefile({ "describe('x', () => { it('y', () => {}); });" }, nested_lib .. "/src/button.spec.ts")
eq(
  neotest_discovery.nearest_vitest_package(nested_lib .. "/src/button.spec.ts"),
  frontend,
  "nested package should resolve to parent Vitest root"
)
eq(neotest_discovery.npm_is_js_test_package(nested_lib), false, "bare nested package claimed as JS test root")
eq(neotest_discovery.npm_is_js_test_package(frontend), true, "Vitest frontend not treated as JS test root")

eq(
  neotest_discovery.adapter_header_label("neotest-maven:" .. maven_mod),
  "neotest-maven · backend",
  "Maven summary header label"
)
eq(
  neotest_discovery.adapter_header_label("neotest-vitest:" .. frontend),
  "neotest-vitest · frontend",
  "Vitest summary header label"
)
eq(neotest_discovery.runner_tab_label(frontend), "tests: frontend", "runner dock tab label")
eq(neotest_discovery.runner_tab_label(maven_mod), "tests: backend", "Maven dock tab label")
local expected = neotest_discovery.expected_adapter_kinds({
  git_root = jvm_fixture,
  maven = { { dir = maven_mod } },
  gradle = { { root = jvm_fixture } },
  npm = { { dir = frontend }, { dir = analog_pkg } },
})
eq(expected["neotest-maven"], true, "expected Maven adapter missing")
eq(expected["gradle-test"], true, "expected Gradle adapter missing")
eq(expected["neotest-vitest"], true, "expected Vitest adapter missing")
eq(expected["neotest-jest"], nil, "Jest expected alongside Vitest")
eq(expected["neotest-rust"], nil, "Rust expected without Cargo.toml")
ok(
  neotest_discovery.expected_kinds_present({
    "neotest-maven:" .. maven_mod,
    "gradle-test:" .. jvm_fixture,
    "neotest-vitest:" .. frontend,
  }, expected),
  "expected kinds were not treated as present"
)
ok(
  not neotest_discovery.expected_kinds_present({ "neotest-vitest:" .. frontend }, expected),
  "missing Maven/Gradle kinds were treated as ready"
)
-- Root-only trees are not summary-ready even if the kind is registered.
ok(
  not neotest_discovery.expected_kinds_ready({ "neotest-vitest:" .. frontend }, { ["neotest-vitest"] = true }),
  "empty Vitest tree was treated as ready"
)

-- Layout expectations for wow-auction-engine (backend Maven + frontend Analog Vitest).
local auction = "/Users/jonas/Dev/Hobby/wow-auction-engine"
if vim.uv.fs_stat(auction) then
  local auction_ws = require("config.project_tools").discover_workspaces(auction)
  local auction_expected = neotest_discovery.expected_adapter_kinds(auction_ws)
  eq(auction_expected["neotest-maven"], true, "wow-auction-engine should expect Maven")
  eq(auction_expected["neotest-vitest"], true, "wow-auction-engine should expect Vitest")
  eq(auction_expected["neotest-jest"], nil, "wow-auction-engine should not expect Jest")
  eq(neotest_discovery.npm_has_vitest(auction .. "/frontend"), true, "wow-auction-engine frontend Vitest")
  eq(
    neotest_discovery.npm_is_js_test_package(auction .. "/frontend/ethereal-ui"),
    false,
    "ethereal-ui should not be seeded as a JS test root"
  )
  eq(
    neotest_discovery.nearest_vitest_package(auction .. "/frontend/ethereal-ui/src/lib/helpers/chart.spec.ts"),
    auction .. "/frontend",
    "ethereal-ui specs belong to frontend Vitest"
  )
  eq(
    neotest_discovery.adapter_header_label("neotest-maven:" .. auction .. "/backend"),
    "neotest-maven · backend",
    "wow-auction-engine Maven header"
  )
  eq(
    neotest_discovery.adapter_header_label("neotest-vitest:" .. auction .. "/frontend"),
    "neotest-vitest · frontend",
    "wow-auction-engine Vitest header"
  )
end

vim.fn.delete(jvm_fixture, "rf")

require("lazy").load({ plugins = { "overseer.nvim", "neotest" } })
local overseer_consumer = require("neotest.consumers.overseer")
ok(type(overseer_consumer) == "table" and overseer_consumer.run ~= nil, "Overseer neotest consumer missing")
local alias = require("overseer.component").get_alias("default_neotest")
ok(type(alias) == "table" and #alias > 0, "default_neotest component alias was not registered")
local function alias_contains(alias_name)
  for _, component in ipairs(require("overseer.component").get_alias(alias_name) or {}) do
    local name = type(component) == "string" and component or component[1]
    if name == "display_duration" or name == "on_output_summarize" then
      return true
    end
  end
  return false
end
ok(not alias_contains("default"), "default alias still uses deprecated render components")
ok(not alias_contains("default_neotest"), "default_neotest alias still uses deprecated render components")
ok(type(require("overseer.config").task_list.render) == "function", "Overseer task renderer missing")

local label_buf = vim.api.nvim_create_buf(false, true)
vim.b[label_buf].tool_panel_label = "tests: backend"
local panel_for_label = require("config.tool_panel")
local label_win = panel_for_label.show_buf(label_buf, { focus = false })
ok(panel_for_label.winbar(label_win):find("tests: backend", 1, true), "custom tool panel label missing")

-- Docked terminal joins the same tab group (does not create a second bottom stack).
require("lazy").load({ plugins = { "snacks.nvim" } })
local term_bufnr = panel_for_label.toggle_terminal({ count = 1, focus = false })
ok(type(term_bufnr) == "number" and vim.api.nvim_buf_is_valid(term_bufnr), "dock terminal buffer missing")
eq(vim.b[term_bufnr].tool_panel_label, "terminal", "dock terminal label")
local dock_state = panel_for_label._state()
ok(
  dock_state.primary_win
    and vim.api.nvim_win_is_valid(dock_state.primary_win),
  "dock primary missing after terminal toggle"
)
eq(vim.api.nvim_win_get_buf(dock_state.primary_win), term_bufnr, "terminal not shown in dock primary")
local bottom_output_wins = 0
for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
  if vim.w[win].tool_panel_role == "output" then
    bottom_output_wins = bottom_output_wins + 1
  end
end
eq(bottom_output_wins, 1, "terminal created an extra output split")
panel_for_label.close()

local maven_adapter = require("config.neotest_maven")
local class_name, method = maven_adapter._class_and_method("net.example.FooTest.works")
eq(class_name, "net.example.FooTest", "Maven class filter")
eq(method, "works", "Maven method filter")
local maven_tree = {
  iter = function()
    return ipairs({
      { type = "namespace", id = "net.example.FooTest", path = "/tmp/FooTest.kt" },
      { type = "test", id = "net.example.FooTest.works", path = "/tmp/FooTest.kt" },
    })
  end,
}
eq(
  maven_adapter._surefire_filter(maven_tree, { type = "test", id = "net.example.FooTest.works" }),
  "net.example.FooTest#works",
  "Maven -Dtest method filter"
)
eq(
  maven_adapter._surefire_filter(maven_tree, { type = "namespace", id = "net.example.FooTest" }),
  "net.example.FooTest",
  "Maven -Dtest class filter"
)

local panel_status = require("config.tool_panel")
local status_sidebar = panel_status.ensure_sidebar("tests", { focus = false })
panel_status.set_tests_status("Discovering tests…")
ok(
  vim.api.nvim_get_option_value("winbar", { win = status_sidebar }):find("Discovering", 1, true),
  "tests rail loading status missing"
)
panel_status.set_tests_status(nil)
eq(vim.api.nvim_get_option_value("winbar", { win = status_sidebar }), "", "tests rail status was not cleared")
vim.api.nvim_win_close(status_sidebar, true)

require("lazy").load({ plugins = { "neotest", "neotest-gradle" } })
local gradle_results = require("config.neotest_gradle")
local native_ids = gradle_results._candidate_ids({
  _attr = {
    classname = "iosSimulatorArm64Test.net.example.ExampleTest",
    name = "works[iosSimulatorArm64]",
  },
})
ok(vim.list_contains(native_ids, "net.example.ExampleTest.works"), "native test ID prefix was not removed")

local merged = {}
gradle_results._merge_result(merged, "example", { status = "failed" })
gradle_results._merge_result(merged, "example", { status = "passed" })
eq(merged.example.status, "failed", "cross-platform pass overwrote a failed test result")

local gradle_fixture_root = vim.fn.tempname()
local gradle_fixture_module = gradle_fixture_root .. "/module"
local native_results = gradle_fixture_module .. "/build/test-results/iosSimulatorArm64Test"
local jvm_results = gradle_fixture_module .. "/build/test-results/jvmTest"
vim.fn.mkdir(native_results, "p")
vim.fn.mkdir(jvm_results, "p")
vim.fn.writefile({ "plugins {}" }, gradle_fixture_module .. "/build.gradle.kts")
local fixture_test_path = gradle_fixture_module .. "/ExampleTest.kt"
vim.fn.writefile({ "package net.example", "class ExampleTest" }, fixture_test_path)
vim.fn.writefile({
  '<testsuite name="net.example.ExampleTest">',
  '  <testcase name="works" classname="net.example.ExampleTest"/>',
  "</testsuite>",
}, jvm_results .. "/TEST-ExampleTest.xml")
vim.fn.writefile({
  '<testsuite name="iosSimulatorArm64Test.net.example.ExampleTest">',
  '  <testcase name="works[iosSimulatorArm64]" classname="iosSimulatorArm64Test.net.example.ExampleTest">',
  '    <failure message="bad" type="AssertionError">AssertionError</failure>',
  "  </testcase>",
  "</testsuite>",
}, native_results .. "/TEST-ExampleTest.xml")

local fixture_positions = {
  { id = gradle_fixture_root, path = gradle_fixture_root, type = "dir" },
  { id = "net.example.ExampleTest.works", path = fixture_test_path, type = "test" },
  { id = "net.example.DeviceTest.waits", path = fixture_test_path, type = "test" },
}
local fixture_tree = {
  data = function()
    return fixture_positions[1]
  end,
  iter = function()
    return ipairs(fixture_positions)
  end,
}
local fixture_results
require("nio").run(function()
  fixture_results = gradle_results.results({
    context = {
      project_directory = gradle_fixture_root,
      test_task = "allTests",
      suite = true,
    },
  }, { code = 1 }, fixture_tree)
end)
ok(vim.wait(2000, function()
  return fixture_results ~= nil
end, 10), "Gradle XML fixture timed out")
eq(fixture_results["net.example.ExampleTest.works"].status, "failed", "native failure was not retained")
eq(fixture_results["net.example.DeviceTest.waits"].status, "skipped", "unrunnable test was falsely failed")
vim.fn.delete(gradle_fixture_root, "rf")

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

dofile(vim.fs.dirname(debug.getinfo(1, "S").source:sub(2)) .. "/neotest_runner.lua")

print("nvim headless tests: ok")
