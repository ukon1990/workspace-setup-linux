local tool_panel = require("config.tool_panel")
local discovery = require("config.neotest_discovery")

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
  desc = "Name Neotest tasks by project folder and show them in the tool panel",
  constructor = function()
    return {
      on_pre_start = function(_, task)
        local label = discovery.runner_tab_label(task.cwd)
        task.name = label
      end,
      on_start = function(_, task)
        local label = discovery.runner_tab_label(task.cwd)
        task.name = label
        vim.schedule(function()
          local bufnr = task:get_bufnr()
          if bufnr and vim.api.nvim_buf_is_valid(bufnr) then
            vim.b[bufnr].tool_panel_label = label
          end
          if show_task(task, false) then
            tool_panel.refresh_tabs()
            return
          end
          vim.defer_fn(function()
            local buf = task:get_bufnr()
            if buf and vim.api.nvim_buf_is_valid(buf) then
              vim.b[buf].tool_panel_label = label
            end
            show_task(task, false)
            tool_panel.refresh_tabs()
          end, 50)
        end)
      end,
    }
  end,
}
