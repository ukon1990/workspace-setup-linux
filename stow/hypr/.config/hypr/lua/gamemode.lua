-- Game mode: strip compositor effects while playing, restore them afterwards.
local M = {}

local home = os.getenv("HOME")
local hook = home .. "/.config/hypr/scripts/game-mode.sh"

local GAME_VALUES = {
	["animations.enabled"] = false,
	["decoration.blur.enabled"] = false,
	["decoration.shadow.enabled"] = false,
	["decoration.rounding"] = 0,
	["general.gaps_in"] = 0,
	["general.gaps_out"] = 0,
	["general.border_size"] = 0,
}

local saved = nil

function M.is_on()
	return saved ~= nil
end

function M.set(on)
	if on == M.is_on() then
		return
	end
	if on then
		saved = {}
		for key in pairs(GAME_VALUES) do
			saved[key] = hl.get_config(key)
		end
		hl.config(GAME_VALUES)
	else
		hl.config(saved)
		saved = nil
	end
	hl.exec_cmd(hook .. (on and " on" or " off"))
end

function M.toggle()
	M.set(not M.is_on())
end

-- Follow running games (windows the "games" rule marked with content = "game").
local function is_game(window)
	return window ~= nil and window.content_type == "game"
end

hl.on("window.open", function(window)
	if is_game(window) then
		M.set(true)
	end
end)

hl.on("window.close", function(closing)
	if not is_game(closing) then
		return
	end
	for _, window in ipairs(hl.get_windows()) do
		if is_game(window) and window.address ~= closing.address then
			return
		end
	end
	M.set(false)
end)

-- A config reload restores the compositor defaults; clear stale side effects too.
hl.exec_cmd(hook .. " off")

return M
