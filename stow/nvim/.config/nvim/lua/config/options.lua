vim.g.mapleader = " "
vim.g.maplocalleader = "\\"

local opt = vim.opt

opt.number = true
opt.relativenumber = true
opt.mouse = "a"
-- Custom RightMouse handlers (explorer, neotest); avoid Neovim's built-in popup.
opt.mousemodel = "extend"
opt.clipboard = "unnamedplus"
opt.undofile = true
opt.swapfile = false
opt.backup = false
opt.ignorecase = true
opt.smartcase = true
opt.signcolumn = "yes"
opt.splitright = true
opt.splitbelow = true
opt.termguicolors = true
opt.scrolloff = 8
opt.sidescrolloff = 8
opt.updatetime = 250
opt.timeoutlen = 300
opt.completeopt = "menu,menuone,noselect"
opt.expandtab = true
opt.shiftwidth = 2
opt.tabstop = 2
opt.smartindent = true
opt.wrap = false
opt.linebreak = false
opt.cursorline = true
opt.list = true
opt.listchars = { tab = "» ", trail = "·", nbsp = "␣" }
opt.fillchars = { eob = " " }
opt.confirm = true
opt.pumheight = 12

-- Prefer dark theme; colorscheme plugin will set the palette
vim.o.background = "dark"
