-- DK64 (US) "only the last sphere can touch the portal" test, for BizHawk.
--
-- Theory (from the decomp): for every prop, func_global_asm_8066F4AC tests the player's active
-- spheres one after another (func_global_asm_80673708). Each of those calls starts by clearing the
-- touch value D_global_asm_807FB601, and the prop only reads it after the loop. So a later sphere
-- that misses wipes out an earlier sphere's touch, and only the last tested sphere can trigger the
-- B. Locker portal.
--
-- Experiment: 8066F4AC skips any sphere whose flag byte (LedgeInfo8C +0x27) has bit 0x04 set,
-- for props only (map walls use bit 0x01, so walking and wall pushes are unchanged). This script
-- sets that bit on every sphere numbered ABOVE a cutoff you choose, so the sphere at the cutoff
-- becomes the last one tested.
--
-- Predictions, if the theory is right:
--   Diddy 0xE7, cutoff 11  -> the tail tip (#11) now triggers the portal (normally it never does)
--   Lanky 0x17A, cutoff 7  -> #7 triggers the portal on the updates where it overlaps
--   cutoff off (0)         -> the game behaves normally (Diddy never touches)
--
-- Keys:  K  experiment on / off      [ and ]  move the cutoff down / up
-- Every touch (control state becomes 0x87) is printed to the Lua console with the cutoff in use.
-- In the Aztec lobby it also shows each sphere's gap to the portal, and prints a console line for
-- every game update in which an active sphere overlaps it (and whether a touch should follow).
-- If no such line appears, the attack simply missed the portal and the test says nothing.
-- The script restores the original flag bytes when the experiment is turned off or the script stops.

memory.usememorydomain("RDRAM")

local PLAYER_PTR = 0x807FBB4C   -- gPlayerPointer
local MAX_SPHERES = 16
local SKIP_PROPS = 0x04         -- LedgeInfo8C +0x27 bit tested by func_global_asm_8066F4AC

local function a(p) return p % 0x800000 end
local function valid(p) return p >= 0x80000000 and p < 0x80800000 end
local function u32(p) return memory.read_u32_be(a(p)) end
local function s16(p) return memory.read_s16_be(a(p)) end
local function u8(p) return memory.read_u8(a(p)) end
local function f32(p) return memory.readfloat(a(p), true) end
local function w8(p, v) memory.write_u8(a(p), v) end
-- (no bit operators: they don't parse in the Lua 5.1 of older BizHawk builds)
local function hasSkip(v) return math.floor(v / SKIP_PROPS) % 2 == 1 end
local function withSkip(v) return hasSkip(v) and v or v + SKIP_PROPS end

-- Aztec lobby (map 0xAD) portal touch triangles in world space (prop 0x2AD, touch flag 0x02);
-- used to show how far each sphere is from the portal, so a miss can be told apart from a failed test
local PORTAL_MAP = 0xAD
local PORTAL = {
	{ { 540.892, 80, 712.022 }, { 461.892, 80, 712.022 }, { 461.892, 130, 712.022 } },
	{ { 540.892, 80, 712.022 }, { 461.892, 130, 712.022 }, { 540.892, 130, 712.022 } },
	{ { 540.892, 130, 712.022 }, { 501.892, 130, 712.022 }, { 501.892, 154, 712.022 } },
	{ { 501.892, 154, 712.022 }, { 501.892, 130, 712.022 }, { 461.892, 130, 712.022 } },
}

local function sub(u, v) return { u[1] - v[1], u[2] - v[2], u[3] - v[3] } end
local function dot(u, v) return u[1] * v[1] + u[2] * v[2] + u[3] * v[3] end
local function len(u) return math.sqrt(dot(u, u)) end
-- distance from point p to triangle t (closest-point test, Ericson's Real-Time Collision Detection)
local function triDist(p, t)
	local A, B, C = t[1], t[2], t[3]
	local ab, ac, ap = sub(B, A), sub(C, A), sub(p, A)
	local d1, d2 = dot(ab, ap), dot(ac, ap)
	if d1 <= 0 and d2 <= 0 then return len(ap) end
	local bp = sub(p, B); local d3, d4 = dot(ab, bp), dot(ac, bp)
	if d3 >= 0 and d4 <= d3 then return len(bp) end
	local vc = d1 * d4 - d3 * d2
	if vc <= 0 and d1 >= 0 and d3 <= 0 then
		local v = d1 / (d1 - d3); return len(sub(p, { A[1] + v * ab[1], A[2] + v * ab[2], A[3] + v * ab[3] }))
	end
	local cp = sub(p, C); local d5, d6 = dot(ab, cp), dot(ac, cp)
	if d6 >= 0 and d5 <= d6 then return len(cp) end
	local vb = d5 * d2 - d1 * d6
	if vb <= 0 and d2 >= 0 and d6 <= 0 then
		local w = d2 / (d2 - d6); return len(sub(p, { A[1] + w * ac[1], A[2] + w * ac[2], A[3] + w * ac[3] }))
	end
	local va = d3 * d6 - d5 * d4
	if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0 then
		local w = (d4 - d3) / ((d4 - d3) + (d5 - d6)); local bc = sub(C, B)
		return len(sub(p, { B[1] + w * bc[1], B[2] + w * bc[2], B[3] + w * bc[3] }))
	end
	local n = { ab[2] * ac[3] - ab[3] * ac[2], ab[3] * ac[1] - ab[1] * ac[3], ab[1] * ac[2] - ab[2] * ac[1] }
	return math.abs(dot(ap, n)) / len(n)
end
-- how far the sphere's surface is from the portal (negative = overlapping), or nil off the Aztec lobby
local function portalGap(node)
	if memory.read_u32_be(a(0x8076A0A8)) ~= PORTAL_MAP then return nil end
	local p = { memory.read_s32_be(a(node + 0x10)) / 8, memory.read_s32_be(a(node + 0x14)) / 8, memory.read_s32_be(a(node + 0x18)) / 8 }
	local best = math.huge
	for _, t in ipairs(PORTAL) do best = math.min(best, triDist(p, t)) end
	return best - memory.read_s32_be(a(node + 0x1C)) / 8
end

local enabled = true
local cutoff = 11
local original = {}             -- node address -> flag byte before we touched it
local resetSeen = false         -- the game cleared our bit since the last frame
local lastState, prevKeys, lastUpdate = nil, {}, nil

-- the player's sphere nodes in list order (sphere #1 first)
local function nodes()
	local out = {}
	local player = u32(PLAYER_PTR)
	if not valid(player) then return out end
	local ledge = u32(player + 0x140)
	if not valid(ledge) then return out end
	local node = u32(ledge + 0x8C)
	while valid(node) and #out < MAX_SPHERES do
		out[#out + 1] = node
		node = u32(node + 0x28)
	end
	return out
end

local function restore()
	for node, v in pairs(original) do
		if valid(node) then w8(node + 0x27, v) end
	end
	original = {}
end

local function apply(list)
	for i, node in ipairs(list) do
		local flags = u8(node + 0x27)
		if i > cutoff then
			if original[node] == nil then original[node] = flags
			elseif not hasSkip(flags) then resetSeen = true end
			w8(node + 0x27, withSkip(flags))
		elseif original[node] ~= nil then
			w8(node + 0x27, original[node]); original[node] = nil
		end
	end
end

event.onexit(restore)
console.clear()
print("last-sphere test loaded: K toggles, [ ] change the cutoff")

while true do
	local keys = input.get()
	local function pressed(k) return keys[k] and not prevKeys[k] end
	if pressed("K") then enabled = not enabled; if not enabled then restore() end end
	if pressed("LeftBracket") then cutoff = math.max(1, cutoff - 1); restore() end
	if pressed("RightBracket") then cutoff = math.min(MAX_SPHERES, cutoff + 1); restore() end
	prevKeys = keys

	local list = nodes()
	if enabled then apply(list) end

	-- report touches
	local player = u32(PLAYER_PTR)
	local state, anim, frame = nil, -1, -1
	if valid(player) then
		state = u8(player + 0x154)
		local aas = u32(player + 0x04)
		if valid(aas) then
			local layer = u32(aas)
			if valid(layer) then anim = s16(layer + 0x10); frame = f32(layer + 0x04) end
		end
		if state == 0x87 and lastState ~= 0x87 then
			print(string.format("TOUCH at emu frame %d: anim 0x%X frame %.2f, experiment %s, cutoff #%d",
				emu.framecount(), (anim + 65536) % 65536, frame, enabled and "ON" or "off", cutoff))
		end
	end
	lastState = state

	-- one console line per game update in which any active sphere overlaps the portal:
	-- which spheres overlap, which one the game tests last, and so whether a touch is expected
	local upd = memory.read_u32_be(a(0x8076A064))
	if upd ~= lastUpdate then
		lastUpdate = upd
		local over, lastTested = {}, nil
		for i, node in ipairs(list) do
			local r = memory.read_s32_be(a(node + 0x1C))
			if u8(node + 0x26) ~= 0 and r ~= 0 then
				if not hasSkip(u8(node + 0x27)) then lastTested = i end
				local g = portalGap(node)
				if g and g < 0 then over[#over + 1] = string.format("#%d by %.2f", i, -g) end
			end
		end
		if #over > 0 then
			local lastHits = false
			for _, o in ipairs(over) do if lastTested and o:match("^#(%d+)") == tostring(lastTested) then lastHits = true end end
			print(string.format("update %d anim 0x%X f%.2f: overlapping %s; last tested #%s -> touch expected %s",
				upd, (anim + 65536) % 65536, frame, table.concat(over, ", "), tostring(lastTested), lastHits and "YES" or "no"))
		end
	end

	-- on-screen status
	gui.text(10, 10, string.format("last-sphere test: %s  cutoff #%d  (K toggle, [ ] cutoff)",
		enabled and "ON" or "off", cutoff))
	gui.text(10, 26, string.format("anim 0x%X  frame %.2f  state 0x%02X",
		(anim + 65536) % 65536, frame, state or 0))
	local y = 42
	for i, node in ipairs(list) do
		local active, r = u8(node + 0x26), memory.read_s32_be(a(node + 0x1C)) / 8
		if active ~= 0 and r > 0 then
			local skipped = hasSkip(u8(node + 0x27))
			local g = portalGap(node)
			gui.text(10, y, string.format("#%d active  r %.2f  %s%s", i, r,
				skipped and "skipped for props" or "tested",
				g and string.format("  portal gap %.2f%s", g, g < 0 and " OVERLAP" or "") or ""))
			y = y + 16
		end
	end
	if resetSeen then
		gui.text(10, y + 4, "warning: the game clears flag +0x27 each update, so the test may not hold")
	end
	emu.frameadvance()
end
