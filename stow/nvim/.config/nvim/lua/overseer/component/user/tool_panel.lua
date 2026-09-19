local tool_panel = require("config.tool_panel")

---@param task overseer.Task
---@param focus boolean|nil
local function show_task(task, focus)
  local bufnr = task:get_bufnr()
  if bufnr and vim.api.nvim_buf_is_valid(bufnr) then
    tool_panel.show_buf(bufnr, { focus = focus ~= false })
    return true
  end
  return false
end

---@type overseer.ComponentFileDefinition
return {
  desc = "Show task output in the shared bottom tool panel",
  constructor = function()
    return {
      on_start = function(_, task)
        vim.schedule(function()
          if show_task(task, false) then
            return
          end
          -- Terminal buf can lag a tick behind on_start
          vim.defer_fn(function()
            show_task(task, false)
          end, 50)
        end)
      end,
    }
  end,
}
