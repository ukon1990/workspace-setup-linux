local M = {}
local actions = {}

function M.bind(keys, description, action, opts)
	opts = opts or {}
	opts.description = description

	local keybind = hl.bind(keys, action, opts)
	local id = ("%d:%s"):format(keybind.modmask, keybind.key)
	if actions[id] then
		error("duplicate hotkey action: " .. id)
	end
	actions[id] = action

	return keybind
end

function M.execute(id)
	local action = actions[id]
	if not action then
		error("unknown hotkey action: " .. id)
	end
	hl.dispatch(action)
end

return M
