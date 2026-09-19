-- Fixes for winbuf.nvim quirks with Neovim splits:
-- 1. Window-local vars are copied on split (often the same table) so all panes
--    share one buffer list and appear to switch together.
-- 2. Empty unnamed buffers ([No Name]) get tracked; skip them unless modified.

local M = {}
local setup_done = false

---@param buf integer
---@return boolean
local function is_tool_buffer(buf)
  if not vim.api.nvim_buf_is_valid(buf) then
    return true
  end
  local ft = vim.bo[buf].filetype
  return vim.bo[buf].buftype ~= ""
    or ft == "OverseerList"
    or ft == "neotest-summary"
    or ft == "neotest-output-panel"
end

---@param buf integer
---@return boolean
local function is_scratch_empty(buf)
  if not vim.api.nvim_buf_is_valid(buf) then
    return false
  end
  if vim.bo[buf].buftype ~= "" then
    return false
  end
  if vim.api.nvim_buf_get_name(buf) ~= "" then
    return false
  end
  if vim.bo[buf].modified then
    return false
  end
  return true
end

function M.setup()
  if setup_done then
    return
  end
  setup_done = true
  local tracker = require("winbuf.tracker")
  local render = require("winbuf.render")
  local pending = {} ---@type table<integer, boolean>
  local scratch_candidates = {} ---@type table<integer, boolean>

  -- winbuf owns normal editor winbars, while config.tool_panel owns output
  -- dock winbars. winbuf refreshes asynchronously after BufEnter and clears
  -- winbars for terminal/nofile buffers, so restore the dock winbars after
  -- every winbuf render pass rather than racing its scheduled callback.
  local original_refresh_all = render.refresh_all
  render.refresh_all = function()
    original_refresh_all()
    local tool_panel = package.loaded["config.tool_panel"]
    if tool_panel then
      tool_panel.refresh_tabs()
    end
  end

  local orig_add = tracker.add_buf_to_win
  tracker.add_buf_to_win = function(win, buf)
    if is_scratch_empty(buf) or is_tool_buffer(buf) then
      return
    end
    return orig_add(win, buf)
  end

  local group = vim.api.nvim_create_augroup("WinBufFix", { clear = true })

  vim.api.nvim_create_autocmd({ "BufAdd", "BufEnter" }, {
    group = group,
    callback = function(event)
      if is_scratch_empty(event.buf) then
        scratch_candidates[event.buf] = true
      else
        scratch_candidates[event.buf] = nil
      end
    end,
  })

  vim.api.nvim_create_autocmd({ "BufDelete", "BufWipeout" }, {
    group = group,
    callback = function(event)
      scratch_candidates[event.buf] = nil
    end,
  })

  -- Give each new split a fresh buffer list (break shared table reference).
  vim.api.nvim_create_autocmd("WinNew", {
    group = group,
    callback = function()
      local win = vim.api.nvim_get_current_win()
      local cfg = vim.api.nvim_win_get_config(win)
      if cfg.relative and cfg.relative ~= "" then
        return
      end
      tracker.set_win_bufs(win, {})
      pending[win] = true
    end,
  })

  -- After the new window settles on its real buffer, track only that buffer.
  vim.api.nvim_create_autocmd("BufEnter", {
    group = group,
    callback = function()
      local win = vim.api.nvim_get_current_win()
      if not pending[win] then
        return
      end
      pending[win] = nil

      local buf = vim.api.nvim_get_current_buf()
      if is_tool_buffer(buf) then
        return
      end
      if is_scratch_empty(buf) then
        tracker.set_win_bufs(win, {})
      else
        tracker.set_win_bufs(win, { buf })
      end
      require("winbuf").refresh()
    end,
  })

  -- Drop only known orphan scratch buffers. Avoid an O(all buffers) scan on
  -- every BufEnter, which becomes noticeable in long-lived sessions.
  vim.api.nvim_create_autocmd("BufEnter", {
    group = group,
    callback = function(ev)
      if is_scratch_empty(ev.buf) then
        return
      end
      for b in pairs(scratch_candidates) do
        if b ~= ev.buf and is_scratch_empty(b) and vim.bo[b].buflisted then
          local wins = vim.fn.win_findbuf(b)
          if #wins == 0 then
            pcall(vim.api.nvim_buf_delete, b, { force = true })
          else
            for _, w in ipairs(wins) do
              tracker.remove_buf_from_win(w, b)
            end
          end
        else
          scratch_candidates[b] = nil
        end
      end
      require("winbuf").refresh()
    end,
  })

  -- Clean any [No Name] tabs already stuck from before this fix loaded.
  vim.schedule(function()
    for _, win in ipairs(vim.api.nvim_list_wins()) do
      local bufs = tracker.get_win_bufs(win)
      local kept = {}
      for _, b in ipairs(bufs) do
        if not is_scratch_empty(b) then
          table.insert(kept, b)
        end
      end
      tracker.set_win_bufs(win, kept)
    end
    for _, buf in ipairs(vim.api.nvim_list_bufs()) do
      if is_scratch_empty(buf) then
        scratch_candidates[buf] = true
      end
    end
    require("winbuf").refresh()
  end)
end

return M
