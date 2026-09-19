-- Fixes for winbuf.nvim quirks with Neovim splits:
-- 1. Window-local vars are copied on split (often the same table) so all panes
--    share one buffer list and appear to switch together.
-- 2. Empty unnamed buffers ([No Name]) get tracked; skip them unless modified.

local M = {}

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
  local tracker = require("winbuf.tracker")
  local pending = {} ---@type table<integer, boolean>

  local orig_add = tracker.add_buf_to_win
  tracker.add_buf_to_win = function(win, buf)
    if is_scratch_empty(buf) then
      return
    end
    return orig_add(win, buf)
  end

  local group = vim.api.nvim_create_augroup("WinBufFix", { clear = true })

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
      if vim.bo[buf].buftype ~= "" then
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

  -- Drop orphan empty unnamed buffers once a real file is open.
  vim.api.nvim_create_autocmd("BufEnter", {
    group = group,
    callback = function(ev)
      if is_scratch_empty(ev.buf) then
        return
      end
      for _, b in ipairs(vim.api.nvim_list_bufs()) do
        if b ~= ev.buf and is_scratch_empty(b) and vim.bo[b].buflisted then
          local wins = vim.fn.win_findbuf(b)
          if #wins == 0 then
            pcall(vim.api.nvim_buf_delete, b, { force = true })
          else
            for _, w in ipairs(wins) do
              tracker.remove_buf_from_win(w, b)
            end
          end
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
    require("winbuf").refresh()
  end)
end

return M
