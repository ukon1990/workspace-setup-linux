-- Tabpage-scoped activity rail and output dock for Overseer + neotest.

local M = {}

local DEFAULT_HEIGHT = 14
local DEFAULT_SIDEBAR_WIDTH = 45
local MAX_HISTORY = 12

---@class ToolPanelState
---@field primary_win? integer
---@field output_wins integer[]
---@field history integer[]
---@field slots? table<string, integer>
---@field sidebar_win? integer
---@field sidebar_kind? "tasks"|"tests"
---@field tests_status? string

---@type table<integer, ToolPanelState>
local states = {}
local setup_done = false

---@param id integer|nil
---@return boolean
local function win_ok(id)
  return type(id) == "number" and vim.api.nvim_win_is_valid(id)
end

local function is_editor_win(win)
  if not win_ok(win) or vim.w[win].tool_panel then
    return false
  end
  local buf = vim.api.nvim_win_get_buf(win)
  return vim.bo[buf].buftype == ""
end

---@param tab? integer
---@return ToolPanelState
local function state_for(tab)
  tab = tab or vim.api.nvim_get_current_tabpage()
  local state = states[tab]
  if not state then
    state = { output_wins = {}, history = {} }
    states[tab] = state
  end
  return state
end

--- Resolve the most recently used normal editor window, excluding tool panes.
---@return integer?
function M.editor_win()
  local alternate = vim.fn.win_getid(vim.fn.winnr("#"))
  if is_editor_win(alternate) then
    return alternate
  end
  local current = vim.api.nvim_get_current_win()
  if is_editor_win(current) then
    return current
  end
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
    if is_editor_win(win) then
      return win
    end
  end
end

--- Open a source location without reusing the activity rail or output dock.
---@param bufnr integer
---@param line? integer zero-indexed
---@param column? integer zero-indexed
---@return boolean
function M.open_in_editor(bufnr, line, column)
  local win = M.editor_win()
  if not win or not vim.api.nvim_buf_is_valid(bufnr) then
    return false
  end
  vim.api.nvim_win_set_buf(win, bufnr)
  if line then
    local last_line = math.max(1, vim.api.nvim_buf_line_count(bufnr))
    local target_line = math.min(math.max(1, line + 1), last_line)
    local text = vim.api.nvim_buf_get_lines(bufnr, target_line - 1, target_line, false)[1] or ""
    local target_column = math.min(math.max(0, column or 0), #text)
    vim.api.nvim_win_set_cursor(win, { target_line, target_column })
  end
  vim.api.nvim_set_current_win(win)
  return true
end

---@param win integer
---@return ToolPanelState
local function state_for_win(win)
  return state_for(vim.api.nvim_win_get_tabpage(win))
end

---@param win integer
---@param bufnr integer
---@return boolean
local function set_win_buf(win, bufnr)
  if not win_ok(win) or not vim.api.nvim_buf_is_valid(bufnr) then
    return false
  end
  pcall(vim.api.nvim_set_option_value, "winfixbuf", false, { scope = "local", win = win })
  local ok, err = pcall(vim.api.nvim_win_set_buf, win, bufnr)
  if not ok then
    vim.notify("tool panel: " .. tostring(err), vim.log.levels.WARN, { title = "tool panel" })
  end
  return ok
end

---@param state ToolPanelState
---@return integer[]
local function prune_history(state)
  local valid = {}
  for _, bufnr in ipairs(state.history) do
    if vim.api.nvim_buf_is_valid(bufnr) then
      table.insert(valid, bufnr)
    end
  end
  state.history = valid
  return valid
end

---@param bufnr integer
---@return string
local function buf_label(bufnr)
  if not vim.api.nvim_buf_is_valid(bufnr) then
    return "?"
  end
  local custom = vim.b[bufnr].tool_panel_label
  if type(custom) == "string" and custom ~= "" then
    return vim.fn.strdisplaywidth(custom) > 32 and (vim.fn.strcharpart(custom, 0, 29) .. "…") or custom
  end
  if vim.bo[bufnr].filetype == "neotest-output-panel" then
    return "tests"
  end
  local title = vim.b[bufnr].term_title
  if type(title) == "string" and title ~= "" then
    title = title:gsub("^%d+:%s*", "")
    return vim.fn.strdisplaywidth(title) > 32 and (vim.fn.strcharpart(title, 0, 29) .. "…") or title
  end
  local name = vim.api.nvim_buf_get_name(bufnr)
  if name:find("Neotest Output", 1, true) then
    return "tests"
  end
  if name ~= "" then
    local short = vim.fn.fnamemodify(name, ":t")
    return vim.fn.strdisplaywidth(short) > 32 and (vim.fn.strcharpart(short, 0, 29) .. "…") or short
  end
  return ("buf %d"):format(bufnr)
end

---@param state ToolPanelState
---@param bufnr integer
local function remember(state, bufnr)
  if not bufnr or not vim.api.nvim_buf_is_valid(bufnr) then
    return
  end
  for i, existing in ipairs(state.history) do
    if existing == bufnr then
      table.remove(state.history, i)
      break
    end
  end
  table.insert(state.history, bufnr)
  while #state.history > MAX_HISTORY do
    table.remove(state.history, 1)
  end
end

local function ensure_highlights()
  vim.api.nvim_set_hl(0, "ToolPanelTab", { link = "TabLine", default = true })
  vim.api.nvim_set_hl(0, "ToolPanelTabSel", { link = "TabLineSel", default = true })
  vim.api.nvim_set_hl(0, "ToolPanelTabFill", { link = "TabLineFill", default = true })
  vim.api.nvim_set_hl(0, "ToolPanelTabSep", { link = "TabLineFill", default = true })
end

local function map_tabs_for_buf(win, buf)
  if not win_ok(win) or not vim.api.nvim_buf_is_valid(buf) then
    return
  end
  local function map(lhs, rhs, desc)
    vim.keymap.set({ "n", "t" }, lhs, rhs, {
      buffer = buf,
      silent = true,
      desc = desc,
      nowait = true,
    })
  end
  map("<S-l>", function()
    M.cycle(1)
  end, "Next tool tab")
  map("<S-h>", function()
    M.cycle(-1)
  end, "Prev tool tab")
  map("gt", function()
    M.cycle(1)
  end, "Next tool tab")
  map("gT", function()
    M.cycle(-1)
  end, "Prev tool tab")
end

---@param win integer
local function mark_output_win(win)
  local state = state_for_win(win)
  vim.w[win].tool_panel = true
  vim.w[win].tool_panel_role = "output"
  vim.wo[win].winfixheight = true
  vim.wo[win].winfixbuf = false
  vim.wo[win].number = false
  vim.wo[win].relativenumber = false
  vim.wo[win].signcolumn = "no"
  vim.wo[win].wrap = false
  if not vim.tbl_contains(state.output_wins, win) then
    table.insert(state.output_wins, win)
  end
  state.primary_win = state.primary_win or win
  map_tabs_for_buf(win, vim.api.nvim_win_get_buf(win))
end

local function cleanup_states()
  for tab, state in pairs(states) do
    if not vim.api.nvim_tabpage_is_valid(tab) then
      states[tab] = nil
    else
      state.output_wins = vim.tbl_filter(win_ok, state.output_wins)
      if not win_ok(state.primary_win) then
        state.primary_win = state.output_wins[1]
      end
      if not win_ok(state.sidebar_win) then
        state.sidebar_win = nil
        state.sidebar_kind = nil
      end
      prune_history(state)
    end
  end
end

local function setup_once()
  if setup_done then
    return
  end
  setup_done = true
  ensure_highlights()
  local group = vim.api.nvim_create_augroup("ToolPanelLayout", { clear = true })
  vim.api.nvim_create_autocmd("ColorScheme", { group = group, callback = ensure_highlights })
  vim.api.nvim_create_autocmd({ "WinClosed", "TabClosed" }, {
    group = group,
    callback = function()
      vim.schedule(cleanup_states)
    end,
  })
  vim.api.nvim_create_autocmd({ "BufWinEnter", "WinEnter", "TermOpen" }, {
    group = group,
    callback = function()
      local win = vim.api.nvim_get_current_win()
      if vim.w[win].tool_panel_role == "output" then
        pcall(vim.api.nvim_set_option_value, "winfixbuf", false, { scope = "local", win = win })
        map_tabs_for_buf(win, vim.api.nvim_win_get_buf(win))
        M.refresh_tabs()
      end
    end,
  })
end

---@param index integer
function M.on_tab_click(index)
  local win = vim.api.nvim_get_current_win()
  if vim.w[win].tool_panel_role ~= "output" then
    win = M.ensure_win({ focus = true })
  end
  local state = state_for_win(win)
  prune_history(state)
  local bufnr = state.history[tonumber(index)]
  if bufnr and set_win_buf(win, bufnr) then
    pcall(vim.api.nvim_set_current_win, win)
    map_tabs_for_buf(win, bufnr)
    M.refresh_tabs()
  end
end

---@param win integer
---@return string
function M.winbar(win)
  win = tonumber(win)
  if not win_ok(win) or vim.w[win].tool_panel_role ~= "output" then
    return ""
  end
  local state = state_for_win(win)
  prune_history(state)
  if #state.history == 0 then
    return "%#ToolPanelTabFill# output "
  end
  local current = vim.api.nvim_win_get_buf(win)
  local parts = {}
  for i, bufnr in ipairs(state.history) do
    local hl = bufnr == current and "%#ToolPanelTabSel#" or "%#ToolPanelTab#"
    local label = (" " .. buf_label(bufnr):gsub("%%", "%%%%") .. " ")
    table.insert(parts, ("%s%%%d@v:lua.require'config.tool_panel'.on_tab_click@%s%%X"):format(hl, i, label))
    if i < #state.history then
      table.insert(parts, "%#ToolPanelTabSep#│")
    end
  end
  table.insert(parts, "%#ToolPanelTabFill#")
  return table.concat(parts)
end

function M.refresh_tabs()
  ensure_highlights()
  -- winbuf refreshes every window, including inactive tabpages, so restore
  -- every output dock rather than only the currently visible one.
  for _, win in ipairs(vim.api.nvim_list_wins()) do
    if vim.w[win].tool_panel_role == "output" then
      vim.api.nvim_set_option_value(
        "winbar",
        ("%%{%%v:lua.require'config.tool_panel'.winbar(%d)%%}"):format(win),
        { scope = "local", win = win }
      )
    end
  end
end

---@param opts? { focus?: boolean, height?: integer }
---@return integer
function M.ensure_win(opts)
  setup_once()
  cleanup_states()
  opts = opts or {}
  local state = state_for()
  local height = opts.height or DEFAULT_HEIGHT
  local win = state.primary_win
  if not win_ok(win) then
    for _, candidate in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
      if vim.w[candidate].tool_panel_role == "output" then
        win = candidate
        break
      end
    end
  end
  if win_ok(win) then
    state.primary_win = win
    if opts.focus ~= false then
      vim.api.nvim_set_current_win(win)
    end
    pcall(vim.api.nvim_win_set_height, win, height)
    M.refresh_tabs()
    return win
  end

  local previous = vim.api.nvim_get_current_win()
  vim.cmd("botright split")
  win = vim.api.nvim_get_current_win()
  state.primary_win = win
  vim.api.nvim_win_set_height(win, height)
  mark_output_win(win)
  M.refresh_tabs()
  if opts.focus == false and win_ok(previous) then
    vim.api.nvim_set_current_win(previous)
  end
  return win
end

---@param bufnr integer
---@param opts? { focus?: boolean, height?: integer, win?: integer }
---@return integer|nil
function M.show_buf(bufnr, opts)
  setup_once()
  opts = opts or {}
  if not bufnr or not vim.api.nvim_buf_is_valid(bufnr) then
    return nil
  end
  local win = opts.win
  if not win_ok(win) or vim.api.nvim_win_get_tabpage(win) ~= vim.api.nvim_get_current_tabpage() then
    win = M.ensure_win(opts)
  else
    mark_output_win(win)
  end
  local state = state_for_win(win)
  remember(state, bufnr)
  if not set_win_buf(win, bufnr) then
    return nil
  end
  map_tabs_for_buf(win, bufnr)
  if vim.bo[bufnr].buftype == "terminal" then
    pcall(vim.api.nvim_win_call, win, function()
      vim.cmd("normal! G")
    end)
  end
  if opts.focus ~= false then
    pcall(vim.api.nvim_set_current_win, win)
  end
  M.refresh_tabs()
  return win
end

-- Update an owning tab without switching tabs or opening a background dock.
function M.replace_output(key, bufnr, opts)
  opts = opts or {}
  local tab = opts.tab or vim.api.nvim_get_current_tabpage()
  if not vim.api.nvim_tabpage_is_valid(tab) or not vim.api.nvim_buf_is_valid(bufnr) then return end
  setup_once()
  local state = state_for(tab)
  state.slots = state.slots or {}
  local old = state.slots[key]
  state.slots[key] = bufnr
  if opts.label then vim.b[bufnr].tool_panel_label = opts.label end
  local replaced = false
  for i, buf in ipairs(state.history) do
    if buf == old or buf == bufnr then
      state.history[i] = bufnr
      replaced = true
      break
    end
  end
  if not replaced then remember(state, bufnr) end
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tab)) do
    if vim.w[win].tool_panel_role == "output" and (vim.api.nvim_win_get_buf(win) == old or win == state.primary_win) then
      set_win_buf(win, bufnr)
      map_tabs_for_buf(win, bufnr)
    end
  end
  if tab == vim.api.nvim_get_current_tabpage() and not win_ok(state.primary_win) then
    local win = M.ensure_win({ focus = false })
    set_win_buf(win, bufnr)
    map_tabs_for_buf(win, bufnr)
  end
  M.refresh_tabs()
end

---@param delta integer
function M.cycle(delta)
  local win = vim.api.nvim_get_current_win()
  if vim.w[win].tool_panel_role ~= "output" then
    win = M.ensure_win({ focus = true })
  end
  local state = state_for_win(win)
  prune_history(state)
  if #state.history == 0 then
    vim.notify("No tool output yet", vim.log.levels.INFO, { title = "tool panel" })
    return
  end
  local current = vim.api.nvim_win_get_buf(win)
  local index = 1
  for i, bufnr in ipairs(state.history) do
    if bufnr == current then
      index = i
      break
    end
  end
  local next_index = ((index - 1 + delta) % #state.history) + 1
  M.show_buf(state.history[next_index], { focus = true, win = win })
end

function M.split_vertical()
  local win = vim.api.nvim_get_current_win()
  if vim.w[win].tool_panel_role ~= "output" then
    win = M.ensure_win({ focus = true })
  end
  local state = state_for_win(win)
  prune_history(state)
  if #state.history < 2 then
    vim.notify("Need at least two tool outputs to split", vim.log.levels.INFO, { title = "tool panel" })
    return
  end
  local current = vim.api.nvim_win_get_buf(win)
  local other
  for i = #state.history, 1, -1 do
    if state.history[i] ~= current then
      other = state.history[i]
      break
    end
  end
  if not other then
    return
  end
  vim.api.nvim_set_current_win(win)
  vim.cmd("vertical rightbelow split")
  local new_win = vim.api.nvim_get_current_win()
  mark_output_win(new_win)
  M.show_buf(other, { focus = true, win = new_win })
end

---@param kind "tasks"|"tests"
local function close_other_sidebar(kind)
  local state = state_for()
  if not state.sidebar_kind or state.sidebar_kind == kind then
    return
  end
  if state.sidebar_kind == "tasks" and package.loaded.overseer then
    pcall(require("overseer").close)
  elseif state.sidebar_kind == "tests" and package.loaded.neotest then
    pcall(require("neotest").summary.close)
  elseif win_ok(state.sidebar_win) then
    pcall(vim.api.nvim_win_close, state.sidebar_win, true)
  end
  state.sidebar_win = nil
  state.sidebar_kind = nil
end

---@param kind "tasks"|"tests"
---@param opts? { focus?: boolean, width?: integer }
---@return integer
function M.ensure_sidebar(kind, opts)
  setup_once()
  opts = opts or {}
  close_other_sidebar(kind)
  local state = state_for()
  if win_ok(state.sidebar_win) and state.sidebar_kind == kind then
    return state.sidebar_win
  end
  local previous = vim.api.nvim_get_current_win()
  vim.cmd("botright vsplit")
  local win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_width(win, opts.width or DEFAULT_SIDEBAR_WIDTH)
  vim.w[win].tool_panel_role = "sidebar"
  vim.w[win].tool_panel_kind = kind
  vim.wo[win].winfixwidth = true
  vim.wo[win].wrap = false
  state.sidebar_win = win
  state.sidebar_kind = kind
  if opts.focus == false and win_ok(previous) then
    vim.api.nvim_set_current_win(previous)
  end
  if kind == "tests" then
    M.refresh_tests_status()
  end
  return win
end

---@param opts? { focus?: boolean }
function M.show_tests(opts)
  opts = opts or {}
  close_other_sidebar("tests")
  require("neotest").summary.open({ enter = opts.focus == true })
  M.refresh_tests_status()
end

function M.toggle_tests()
  local state = state_for()
  if state.sidebar_kind == "tests" and win_ok(state.sidebar_win) then
    require("neotest").summary.close()
    state.sidebar_win = nil
    state.sidebar_kind = nil
    state.tests_status = nil
    return
  end
  M.show_tests({ focus = true })
end

--- Show a persistent discovery/loading message on the Tests activity rail.
---@param message string|nil
function M.set_tests_status(message)
  local state = state_for()
  state.tests_status = message
  M.refresh_tests_status()
end

function M.refresh_tests_status()
  local state = state_for()
  if not win_ok(state.sidebar_win) or state.sidebar_kind ~= "tests" then
    return
  end
  if state.tests_status and state.tests_status ~= "" then
    vim.api.nvim_set_option_value(
      "winbar",
      "%#ToolPanelTabSel# " .. state.tests_status:gsub("%%", "%%%%") .. " %#ToolPanelTabFill#",
      { scope = "local", win = state.sidebar_win }
    )
  else
    vim.api.nvim_set_option_value("winbar", "", { scope = "local", win = state.sidebar_win })
  end
end

---@param opts? { focus?: boolean }
function M.show_tasks(opts)
  opts = opts or {}
  close_other_sidebar("tasks")
  local win = M.ensure_sidebar("tasks", { focus = false })
  require("overseer").open({ winid = win, enter = opts.focus == true })
end

function M.toggle_tasks()
  local state = state_for()
  if state.sidebar_kind == "tasks" and win_ok(state.sidebar_win) then
    require("overseer").close()
    state.sidebar_win = nil
    state.sidebar_kind = nil
    return
  end
  M.show_tasks({ focus = true })
end

function M.close()
  local state = state_for()
  for _, win in ipairs(vim.deepcopy(state.output_wins)) do
    if win_ok(win) then
      pcall(vim.api.nvim_win_close, win, true)
    end
  end
  state.primary_win = nil
  state.output_wins = {}
end

--- Toggle a Snacks terminal into the shared bottom dock tab group (not a stacked split).
---@param opts? { count?: integer, focus?: boolean }
---@return integer|nil bufnr
function M.toggle_terminal(opts)
  opts = opts or {}
  local count = opts.count or vim.v.count1
  if count < 1 then
    count = 1
  end
  local label = count == 1 and "terminal" or ("terminal " .. tostring(count))

  local Snacks = Snacks or require("snacks")
  local term = Snacks.terminal.get(nil, {
    count = count,
    -- Float so Snacks does not open a second botright stack under the dock.
    win = { position = "float" },
  })
  if not term or not term.buf or not vim.api.nvim_buf_is_valid(term.buf) then
    return nil
  end
  pcall(function()
    term:hide()
  end)

  local bufnr = term.buf
  vim.b[bufnr].tool_panel_label = label

  local state = state_for()
  local win = state.primary_win
  if win_ok(win) and vim.api.nvim_win_get_buf(win) == bufnr then
    prune_history(state)
    local previous
    for i = #state.history, 1, -1 do
      if state.history[i] ~= bufnr then
        previous = state.history[i]
        break
      end
    end
    if previous then
      M.show_buf(previous, { focus = opts.focus ~= false, win = win })
    else
      M.close()
    end
    return bufnr
  end

  M.show_buf(bufnr, { focus = opts.focus ~= false })
  if opts.focus ~= false then
    pcall(vim.cmd.startinsert)
  end
  return bufnr
end

---@return ToolPanelState
function M._state()
  return state_for()
end

return M
