return {
  {
    "folke/snacks.nvim",
    priority = 1000,
    lazy = false,
    opts = {
      bigfile = { enabled = true },
      notifier = { enabled = true },
      quickfile = { enabled = true },
      statuscolumn = { enabled = true },
      words = { enabled = true },
      input = { enabled = true },
      explorer = { enabled = true },
      picker = {
        enabled = true,
        sources = {
          explorer = {
            hidden = true,
            actions = {
              -- Open as a winbuf tab in the focused editor (not a Neovim tabpage —
              -- tabpages hide the explorer and can spawn a second kotlin_lsp).
              explorer_open_tab = function(picker)
                Snacks.picker.actions.jump(picker, nil, { cmd = "edit" })
              end,
              explorer_open_vsplit_left = function(picker)
                local prev = vim.o.splitright
                vim.o.splitright = false
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "vsplit" })
                vim.o.splitright = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_vsplit_right = function(picker)
                local prev = vim.o.splitright
                vim.o.splitright = true
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "vsplit" })
                vim.o.splitright = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_hsplit_up = function(picker)
                local prev = vim.o.splitbelow
                vim.o.splitbelow = false
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "split" })
                vim.o.splitbelow = prev
                if not ok then
                  error(err)
                end
              end,
              explorer_open_hsplit_down = function(picker)
                local prev = vim.o.splitbelow
                vim.o.splitbelow = true
                local ok, err = pcall(Snacks.picker.actions.jump, picker, nil, { cmd = "split" })
                vim.o.splitbelow = prev
                if not ok then
                  error(err)
                end
              end,
              -- Create under picker:dir() (directory item or parent of file), same as explorer_add.
              explorer_new_file = function(picker)
                local Tree = require("snacks.explorer.tree")
                local Actions = require("snacks.explorer.actions")
                Snacks.input({ prompt = "New file name" }, function(value)
                  if not value or value:match("^%s*$") then
                    return
                  end
                  value = value:gsub("/+$", "")
                  local path = vim.fs.normalize(picker:dir() .. "/" .. value)
                  if vim.uv.fs_stat(path) then
                    Snacks.notify.warn("File already exists:\n- `" .. path .. "`")
                    return
                  end
                  local dir = vim.fs.dirname(path)
                  vim.fn.mkdir(dir, "p")
                  io.open(path, "w"):close()
                  Tree:open(dir)
                  Tree:refresh(dir)
                  Actions.update(picker, { target = path })
                end)
              end,
              explorer_new_folder = function(picker)
                local Tree = require("snacks.explorer.tree")
                local Actions = require("snacks.explorer.actions")
                Snacks.input({ prompt = "New folder name" }, function(value)
                  if not value or value:match("^%s*$") then
                    return
                  end
                  value = value:gsub("/+$", "")
                  local path = vim.fs.normalize(picker:dir() .. "/" .. value)
                  if vim.uv.fs_stat(path) then
                    Snacks.notify.warn("Folder already exists:\n- `" .. path .. "`")
                    return
                  end
                  vim.fn.mkdir(path, "p")
                  Tree:open(path)
                  Tree:refresh(path)
                  Actions.update(picker, { target = path })
                end)
              end,
              explorer_open_menu = function(picker)
                -- Resolve the row under the cursor (not the previously focused item).
                local item
                local mp = vim.fn.getmousepos()
                if mp.winid == picker.list.win.win then
                  local idx = picker.list:row2idx(mp.line)
                  if idx and idx > 0 then
                    picker.list:view(idx)
                    item = picker.list:get(idx)
                  end
                end
                item = item or picker:current()
                if not item then
                  return
                end

                local choices
                if item.dir then
                  choices = {
                    { label = "New file", action = "explorer_new_file" },
                    { label = "New folder", action = "explorer_new_folder" },
                    { label = "Delete", action = "explorer_del" },
                  }
                else
                  choices = {
                    { label = "Open in editor tab", action = "explorer_open_tab" },
                    { label = "Open split left", action = "explorer_open_vsplit_left" },
                    { label = "Open split right", action = "explorer_open_vsplit_right" },
                    { label = "Open split up", action = "explorer_open_hsplit_up" },
                    { label = "Open split down", action = "explorer_open_hsplit_down" },
                    { label = "Delete", action = "explorer_del" },
                  }
                end

                -- Defer so list cursor settles before snacks ui.select opens.
                vim.schedule(function()
                  vim.ui.select(choices, {
                    prompt = "Context menu",
                    kind = "explorer_context",
                    format_item = function(choice)
                      return choice.label
                    end,
                  }, function(choice)
                    if choice then
                      picker:action(choice.action)
                    end
                  end)
                end)
              end,
            },
            win = {
              list = {
                keys = {
                  ["<RightMouse>"] = "explorer_open_menu",
                },
              },
            },
          },
        },
      },
      terminal = { enabled = true },
    },
    keys = {
      {
        "<leader>ff",
        function()
          Snacks.picker.files()
        end,
        desc = "Find files",
      },
      {
        "<leader>fg",
        function()
          Snacks.picker.grep()
        end,
        desc = "Grep",
      },
      {
        "<leader>fb",
        function()
          Snacks.picker.buffers()
        end,
        desc = "Buffers",
      },
      {
        "<leader>fh",
        function()
          Snacks.picker.help()
        end,
        desc = "Help pages",
      },
      {
        "<leader>fr",
        function()
          Snacks.picker.recent()
        end,
        desc = "Recent files",
      },
      {
        "<leader>fe",
        function()
          Snacks.explorer()
        end,
        desc = "File explorer",
      },
      {
        "<leader>e",
        function()
          Snacks.explorer()
        end,
        desc = "File explorer",
      },
      {
        "<leader>gg",
        function()
          if vim.fn.executable("lazygit") ~= 1 then
            vim.notify(
              "lazygit is not installed. Install it (e.g. `paru -S lazygit`) then retry.",
              vim.log.levels.WARN,
              { title = "Snacks" }
            )
            return
          end
          Snacks.lazygit()
        end,
        desc = "Lazygit",
      },
      {
        "<leader>n",
        function()
          Snacks.notifier.show_history()
        end,
        desc = "Notification history",
      },
      {
        "<leader>tt",
        function()
          Snacks.terminal()
        end,
        desc = "Toggle terminal (count = id)",
      },
      {
        "<leader>tv",
        function()
          Snacks.terminal(nil, {
            win = { position = "right", stack = false },
          })
        end,
        desc = "Terminal right (side-by-side; count = id)",
      },
      {
        "<leader>th",
        function()
          Snacks.terminal(nil, {
            win = { position = "left", stack = false },
          })
        end,
        desc = "Terminal left (side-by-side; count = id)",
      },
      {
        "<leader>ts",
        function()
          Snacks.terminal(nil, {
            win = { position = "bottom", stack = true },
          })
        end,
        desc = "Terminal bottom stacked (count = id)",
      },
      {
        "<leader>uC",
        function()
          Snacks.picker.colorschemes()
        end,
        desc = "Colorscheme",
      },
      {
        "<leader>ub",
        function()
          local dark = vim.o.background ~= "dark"
          vim.o.background = dark and "dark" or "light"
          local name = vim.g.colors_name or "tokyonight"
          if name:match("^tokyonight") then
            vim.cmd.colorscheme(dark and "tokyonight-night" or "tokyonight-day")
          else
            pcall(vim.cmd.colorscheme, name)
          end
        end,
        desc = "Toggle background",
      },
      {
        "<leader>uN",
        function()
          Snacks.notifier.hide()
        end,
        desc = "Dismiss notifications",
      },
      {
        "<leader>fd",
        function()
          Snacks.picker.diagnostics()
        end,
        desc = "Diagnostics",
      },
      {
        "<leader>xx",
        function()
          Snacks.picker.diagnostics()
        end,
        desc = "Workspace diagnostics",
      },
      {
        "<leader>xX",
        function()
          Snacks.picker.diagnostics_buffer()
        end,
        desc = "Buffer diagnostics",
      },
      {
        "<leader>xq",
        function()
          local qf = vim.fn.getqflist({ size = 0, title = 0 })
          if qf.size == 0 then
            vim.notify("No parsed task errors", vim.log.levels.INFO, { title = "tasks" })
            return
          end
          Snacks.picker.qflist({ title = qf.title ~= "" and qf.title or "Task errors" })
        end,
        desc = "Task errors",
      },
      {
        "<leader>fs",
        function()
          Snacks.picker.lsp_symbols()
        end,
        desc = "LSP symbols",
      },
      {
        "<leader>fk",
        function()
          Snacks.picker.keymaps()
        end,
        desc = "Search keymaps",
      },
      {
        "<C-:>",
        function()
          Snacks.picker.keymaps()
        end,
        desc = "Search keymaps",
        mode = { "n", "i", "v" },
      },
    },
  },
}
