local constants = require("overseer.constants")
local util = require("overseer.util")

---@param task_id integer
---@return integer
local function quickfix_count(task_id)
  local last = vim.fn.getqflist({ nr = "$" }).nr or 0
  for nr = last, 1, -1 do
    local list = vim.fn.getqflist({ nr = nr, context = 0, items = 0 })
    if list.context == task_id then
      return vim.tbl_count(list.items or {})
    end
  end
  return 0
end

---@type overseer.ComponentFileDefinition
return {
  desc = "Notify when a task completes, including its parsed error count",
  constructor = function()
    return {
      on_complete = function(_, task, status)
        if status ~= constants.STATUS.SUCCESS and status ~= constants.STATUS.FAILURE then
          return
        end
        vim.schedule(function()
          local count = quickfix_count(task.id)
          local suffix = count == 1 and "1 issue" or (count .. " issues")
          vim.notify(
            string.format("%s %s · %s", status, task.name, suffix),
            util.status_to_log_level(status),
            { title = "overseer" }
          )
        end)
      end,
    }
  end,
}
