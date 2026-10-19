-- DK64 pointer watches (BizHawk N64 core, DK64 US): RAM watches whose
-- address goes through a pointer, which BizHawk's own watches can't follow.
-- The player actor is allocated at run time; gPlayerPointer is read again
-- every frame, so the watches follow the Kong across map loads, Kong swaps
-- and savestates.
--
-- A window lists the watches with their values. Pick one in the dropdown to:
--   Poke     write the value in the box (0x... for hex; a float for f32)
--   Freeze   write its current value every frame (again: unfreeze)
--   Type     show it as another type (u8 s8 u16 s16 u32 s32 h8 h16 h32 f32)
-- Add a watch at the bottom: base, offset, type, name. Each one added is
-- printed as a WATCHES line to paste below, to keep it.
--
-- Below the watches it also shows what actually happened on the last game
-- update (object_timer changed): how far the Kong moved in x/z and y, and
-- the direction it moved in, next to the speed the game stores.

---------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------

-- N64 pointers are KSEG0 addresses (0x80xxxxxx); minus this, an RDRAM one
local PTR_OFFSET = 0x80000000
local RDRAM_SIZE = 0x800000

local function valid(p) return p >= PTR_OFFSET and p < PTR_OFFSET + RDRAM_SIZE end

-- Where an address starts from: a number is an RDRAM address; a function
-- returns one (nil: not there right now)
local function deref(ptrAddr)
	if ptrAddr < 0 or ptrAddr + 4 > RDRAM_SIZE then return nil end
	local p = mainmemory.read_u32_be(ptrAddr)
	if not valid(p) then return nil end
	return p - PTR_OFFSET
end
local BASES = {
	player = function() return deref(0x7FBB4C) end,                      -- gPlayerPointer (the Kong's Actor)
	anim = function() local p = deref(0x7FBB4C); return p and deref(p + 0x04) end,   -- player->animation_state
	ledge = function() local p = deref(0x7FBB4C); return p and deref(p + 0x140) end, -- player->ledge_info_pointer
	abs = 0,                                                              -- offset = the RDRAM address
}
local BASE_ORDER = { "player", "anim", "ledge", "abs" }

-- The watches: base, offset from it, type, name. `chain` (optional): offsets
-- of pointers to follow first, e.g. { base = "anim", chain = { 0x00 }, off = 0x10 }
-- is the animation file of the current layer.
-- (types: u8 s8 u16 s16 u32 s32, h8 h16 h32 = hex, f32)
local WATCHES = {
	{ base = "player", off = 0x7C, type = "f32", name = "pos x" },
	{ base = "player", off = 0x80, type = "f32", name = "pos y" },
	{ base = "player", off = 0x84, type = "f32", name = "pos z" },
	{ base = "player", off = 0xE6, type = "h16", name = "facing angle (y_rotation)" },
	{ base = "player", off = 0xEE, type = "h16", name = "moving angle" },
	{ base = "player", off = 0xB8, type = "f32", name = "xz speed (forward velocity)" },
	{ base = "player", off = 0xC0, type = "f32", name = "y velocity" },
	{ base = "player", off = 0xC4, type = "f32", name = "y acceleration (gravity)" },
	{ base = "player", off = 0xC8, type = "f32", name = "terminal velocity" },
	{ base = "player", off = 0xA4, type = "f32", name = "floor height" },
	{ base = "player", off = 0xB4, type = "f32", name = "distance from floor" },
	{ base = "player", off = 0x154, type = "h8", name = "control state" },
	{ base = "player", off = 0x155, type = "u8", name = "control state progress" },
	{ base = "anim", chain = { 0x00 }, off = 0x10, type = "h16", name = "animation file" },
	{ base = "anim", chain = { 0x00 }, off = 0x04, type = "f32", name = "animation frame" },
	{ base = "anim", off = 0x48, type = "f32", name = "animation speed (script)" },
	{ base = "anim", off = 0x38, type = "f32", name = "scale" },
	{ base = "ledge", off = 0x0C, type = "s32", name = "broad-phase radius (x8)" },
	{ base = "abs", off = 0x76A0A8, type = "h32", name = "current map" },
	{ base = "abs", off = 0x744478, type = "u32", name = "lag boost (2 = no lag)" },
	{ base = "abs", off = 0x76A064, type = "u32", name = "game updates (object_timer)" },
}

---------------------------------------------------------------------------
-- Memory
---------------------------------------------------------------------------

memory.usememorydomain("RDRAM")

local TYPES = { "u8", "s8", "u16", "s16", "u32", "s32", "h8", "h16", "h32", "f32" }
local SIZE = { u8 = 1, s8 = 1, h8 = 1, u16 = 2, s16 = 2, h16 = 2, u32 = 4, s32 = 4, h32 = 4, f32 = 4 }

local function read(addr, t)
	if t == "u8" or t == "h8" then return mainmemory.read_u8(addr) end
	if t == "s8" then return mainmemory.read_s8(addr) end
	if t == "u16" or t == "h16" then return mainmemory.read_u16_be(addr) end
	if t == "s16" then return mainmemory.read_s16_be(addr) end
	if t == "u32" or t == "h32" then return mainmemory.read_u32_be(addr) end
	if t == "s32" then return mainmemory.read_s32_be(addr) end
	return mainmemory.readfloat(addr, true)
end

-- (the value as written: unsigned types wrap, signed ones too)
local function write(addr, t, v)
	if t == "f32" then mainmemory.writefloat(addr, v, true); return end
	v = math.floor(v + 0.5)
	local size = SIZE[t]
	local mod = 2 ^ (8 * size)
	v = v % mod
	if size == 1 then mainmemory.write_u8(addr, v)
	elseif size == 2 then mainmemory.write_u16_be(addr, v)
	else mainmemory.write_u32_be(addr, v) end
end

local function show(v, t)
	if v == nil then return "-" end
	if t == "f32" then return string.format("%.9g", v) end
	if t == "h8" then return string.format("0x%02X", v) end
	if t == "h16" then return string.format("0x%04X", v) end
	if t == "h32" then return string.format("0x%08X", v) end
	return tostring(v)
end

-- A watch's RDRAM address now, or nil (a null pointer on the way)
local function addrOf(w)
	local b = BASES[w.base]
	if b == nil then b = tonumber(w.base) end
	local a = b
	if type(b) == "function" then a = b() end
	if not a then return nil end
	for _, o in ipairs(w.chain or {}) do
		a = deref(a + o)
		if not a then return nil end
	end
	a = a + w.off
	if a < 0 or a + SIZE[w.type] > RDRAM_SIZE then return nil end
	return a
end

-- "0x1F" / "-5" / "1.5"
local function parseValue(text, t)
	text = text:gsub("^%s+", ""):gsub("%s+$", "")
	local neg, hex = text:match("^(%-?)0[xX](%x+)$")
	if hex then return (neg == "-" and -1 or 1) * tonumber(hex, 16) end
	return tonumber(text)
end

---------------------------------------------------------------------------
-- Movement on the last game update
---------------------------------------------------------------------------

local lastUpdate, lastPos, moved

local function trackMovement()
	local p = BASES.player()
	local t = mainmemory.read_u32_be(0x76A064)
	if not p then lastPos = nil; return end
	local pos = { mainmemory.readfloat(p + 0x7C, true), mainmemory.readfloat(p + 0x80, true), mainmemory.readfloat(p + 0x84, true) }
	if t ~= lastUpdate then
		if lastPos and lastUpdate and t > lastUpdate then
			local dx, dy, dz = pos[1] - lastPos[1], pos[2] - lastPos[2], pos[3] - lastPos[3]
			local xz = math.sqrt(dx * dx + dz * dz)
			-- DK64 angles: 4096 = full turn, 0 = +z, 1024 = +x
			-- (math.atan2 is gone in Lua 5.4; math.atan takes two arguments there)
			local atan2 = math.atan2 or math.atan
			local ang = xz > 1e-4 and math.floor(atan2(dx, dz) * 2048 / math.pi + 0.5) % 4096 or nil
			moved = { xz = xz, dy = dy, ang = ang, updates = t - lastUpdate,
				boost = mainmemory.read_u32_be(0x744478) }
		end
		lastUpdate, lastPos = t, pos
	end
end

---------------------------------------------------------------------------
-- Window
---------------------------------------------------------------------------

console.clear()
local W, H = 560, 700
local closed = false
local form = forms.newform(W, H, "DK64 pointer watches", function() closed = true end)
local list = forms.label(form, "", 8, 8, W - 30, 460, true)

-- (dropdown items get sorted: numbered so they keep the list's order)
local function items()
	local out = {}
	for i, w in ipairs(WATCHES) do out[#out + 1] = string.format("%02d %s", i, w.name) end
	return out
end
local y = 476
forms.label(form, "Watch", 8, y + 3, 50, 20)
local pick = forms.dropdown(form, items(), 60, y, 280, 20)
local function picked()
	local i = tonumber((forms.gettext(pick) or ""):match("^(%d+)"))
	return i and WATCHES[i], i
end

y = y + 30
forms.label(form, "Value", 8, y + 3, 50, 20)
local valueBox = forms.textbox(form, "", 120, 20, nil, 60, y)
forms.button(form, "Poke", function()
	local w = picked()
	if not w then return end
	local v = parseValue(forms.gettext(valueBox), w.type)
	local a = addrOf(w)
	if v == nil then print("not a number: " .. forms.gettext(valueBox)); return end
	if not a then print(w.name .. ": null pointer"); return end
	write(a, w.type, v)
	if w.frozen ~= nil then w.frozen = v end
end, 190, y - 1, 60, 23)
forms.button(form, "Freeze", function()
	local w = picked()
	if not w then return end
	if w.frozen ~= nil then w.frozen = nil; return end
	local a = addrOf(w)
	if a then w.frozen = read(a, w.type) end
end, 255, y - 1, 60, 23)
local typePick = forms.dropdown(form, TYPES, 330, y, 60, 20)
forms.button(form, "Type", function()
	local w = picked()
	if not w then return end
	local t = forms.gettext(typePick)
	-- (frozen: keep the frozen bytes, read back as the new type)
	if w.frozen ~= nil then local a = addrOf(w); if a then w.frozen = read(a, t) end end
	w.type = t
end, 395, y - 1, 50, 23)

-- Add a watch
y = y + 40
forms.label(form, "Add:  base / offset (hex) / type / name", 8, y, 400, 18)
y = y + 22
local basePick = forms.dropdown(form, BASE_ORDER, 8, y, 70, 20)
local offBox = forms.textbox(form, "0x0", 80, 20, nil, 85, y)
local addType = forms.dropdown(form, TYPES, 172, y, 60, 20)
local nameBox = forms.textbox(form, "", 160, 20, nil, 238, y)
forms.button(form, "Add", function()
	local off = tonumber((forms.gettext(offBox):gsub("^0[xX]", "")), 16)
	if not off then print("offset isn't hex: " .. forms.gettext(offBox)); return end
	local w = { base = forms.gettext(basePick), off = off, type = forms.gettext(addType), name = forms.gettext(nameBox) }
	if w.name == "" then w.name = string.format("%s+0x%X", w.base, off) end
	WATCHES[#WATCHES + 1] = w
	forms.setdropdownitems(pick, items())
	print(string.format('\t{ base = "%s", off = 0x%X, type = "%s", name = "%s" },', w.base, w.off, w.type, w.name))
end, 405, y - 1, 50, 23)

---------------------------------------------------------------------------
-- Every frame: freeze, then show
---------------------------------------------------------------------------

event.onexit(function() if not closed then forms.destroy(form) end end)

local lastText
while not closed do
	local lines = {}
	for i, w in ipairs(WATCHES) do
		local a = addrOf(w)
		if a and w.frozen ~= nil then write(a, w.type, w.frozen) end
		local v = a and read(a, w.type)
		lines[#lines + 1] = string.format("%02d %-28s %s %-14s %s", i, w.name:sub(1, 28),
			a and string.format("%08X", a + PTR_OFFSET) or "  null  ", show(v, w.type), w.frozen ~= nil and "F" or "")
	end
	trackMovement()
	lines[#lines + 1] = ""
	if moved then
		lines[#lines + 1] = string.format("last update: moved xz %.3f  y %+.3f  direction %s  (%d update%s, boost %d%s)",
			moved.xz, moved.dy, moved.ang and string.format("0x%03X", moved.ang) or "-",
			moved.updates, moved.updates == 1 and "" or "s", moved.boost, emu.islagged() and ", lag frame" or "")
	else
		lines[#lines + 1] = "last update: -"
	end
	local text = table.concat(lines, "\n")
	if text ~= lastText then forms.settext(list, text); lastText = text end
	emu.frameadvance()
end
