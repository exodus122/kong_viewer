-- DK64 (US) collision sphere logger for BizHawk.
--
-- Every emulated frame it writes one CSV row: the player's position, facing, state and animation,
-- plus every collision sphere's world position, radius and active flag (the LedgeInfo8C list that
-- the wall and prop code tests: func_global_asm_80671880 / 806734E4 / 8066F4AC).
-- It also marks the frame where the map changes (for example when a B. Locker skip enters the level).
--
-- Usage: Tools > Lua Console > open this script. Press L to pause or resume logging.
-- Output: ../results/logs/kong_spheres_<date>.csv (relative to this script).

memory.usememorydomain("RDRAM")

local PLAYER_PTR  = 0x807FBB4C   -- gPlayerPointer
local CURRENT_MAP = 0x8076A0A8   -- current_map (u32)
local LAG_BOOST   = 0x80744478   -- D_global_asm_80744478 (retraces per game update)
local OBJ_TIMER   = 0x8076A064   -- object_timer (counts game updates)

local function a(p) return p % 0x800000 end
local function valid(p) return p >= 0x80000000 and p < 0x80800000 end
local function u32(p) return memory.read_u32_be(a(p)) end
local function s32(p) return memory.read_s32_be(a(p)) end
local function s16(p) return memory.read_s16_be(a(p)) end
local function u16(p) return memory.read_u16_be(a(p)) end
local function u8(p)  return memory.read_u8(a(p)) end
local function f32(p) return memory.readfloat(a(p), true) end

local here = debug.getinfo(1, "S").source:match("^@?(.*[\\/])") or ""
local path = here .. "../results/logs/kong_spheres_" .. os.date("%Y%m%d_%H%M%S") .. ".csv"
local out = assert(io.open(path, "w"))
local MAX_SPHERES = 16
local header = "emu_frame,lagged,game_update,lag_boost,map,map_changed,x,y,z,facing_hex,facing_deg,control_state,anim_file,anim_frame,scale"
for i = 1, MAX_SPHERES do
  header = header .. string.format(",s%d_active,s%d_x,s%d_y,s%d_z,s%d_r", i, i, i, i, i)
end
out:write(header .. ",extra\n")

local logging = true
local prev_keys = {}
local last_map = nil
local rows = 0
event.onexit(function() out:close() end)

local function read_row()
  local player = u32(PLAYER_PTR)
  if not valid(player) then return nil end
  local map = u32(CURRENT_MAP)
  local changed = (last_map ~= nil and map ~= last_map) and 1 or 0
  last_map = map

  local x, y, z = f32(player + 0x7C), f32(player + 0x80), f32(player + 0x84)
  local facing = u16(player + 0xE6) % 4096
  local state = u8(player + 0x154)

  local anim_file, anim_frame, scale = -1, -1, -1
  local aas = u32(player + 0x04)                     -- animation_state
  if valid(aas) then
    scale = f32(aas + 0x38)                          -- scale_y
    local layer = u32(aas + 0x00)                    -- AnimationStateUnk0
    if valid(layer) then
      anim_frame = f32(layer + 0x04)
      anim_file = s16(layer + 0x10)
    end
  end

  local row = string.format("%d,%d,%d,%d,0x%X,%d,%.4f,%.4f,%.4f,0x%03X,%.2f,0x%02X,0x%X,%.3f,%.4f",
    emu.framecount(), emu.islagged() and 1 or 0, u32(OBJ_TIMER), u32(LAG_BOOST), map, changed,
    x, y, z, facing, facing * 360 / 4096, state, (anim_file + 65536) % 65536, anim_frame, scale)

  -- sphere list: ledge_info_pointer (+0x140) -> +0x8C first LedgeInfo8C, linked through +0x28
  local spheres = {}
  local ledge = u32(player + 0x140)
  local node = valid(ledge) and u32(ledge + 0x8C) or 0
  local i = 0
  while valid(node) and i < MAX_SPHERES do
    i = i + 1
    local active = u8(node + 0x26)
    local sx, sy, sz, sr = s32(node + 0x10) / 8, s32(node + 0x14) / 8, s32(node + 0x18) / 8, s32(node + 0x1C) / 8
    spheres[i] = { active = active, x = sx, y = sy, z = sz, r = sr }
    row = row .. string.format(",%d,%.3f,%.3f,%.3f,%.3f", active, sx, sy, sz, sr)
    node = u32(node + 0x28)
  end
  for _ = i + 1, MAX_SPHERES do row = row .. ",,,,," end

  -- extra: everything else func_global_asm_806195D0 reads when it builds bone matrices
  local ex = {}
  if valid(aas) then
    for li = 1, 3 do                                  -- layers unk4 / unk8 / unkC (AnimationStateUnk0)
      local layer = u32(aas + 4 * li)
      if valid(layer) then
        local file = layer ~= 0 and s16(layer + 0x10) or -1
        ex[#ex + 1] = string.format("L%d=0x%X@%.2f", li, (file + 65536) % 65536, f32(layer + 0x04))
      end
    end
    ex[#ex + 1] = string.format("w28=%d w2A=%d blend10=%.3f", u16(aas + 0x28), u16(aas + 0x2A), f32(aas + 0x10))
    local function list(ptr, stride, done, fmt)
      local parts, p, n = {}, ptr, 0
      while valid(p) and n < 8 do
        local s = fmt(p)
        if s == nil then break end
        parts[#parts + 1] = s
        p = p + stride; n = n + 1
      end
      return table.concat(parts, " ")
    end
    -- rotation overrides (8061A1B4): s8 weight (0 ends), u8 channel, s16 x3
    ex[#ex + 1] = "rot1C=" .. list(u32(aas + 0x1C), 8, nil, function(p)
      local w = memory.read_s8(a(p)); if w == 0 then return nil end
      return string.format("w%d:c%d:%d/%d/%d", w, u8(p + 1), s16(p + 2), s16(p + 4), s16(p + 6)) end)
    -- scale overrides (8061A61C) and translation overrides (8061A758): u8 bone a, u8 bone b (0xFF ends), f32 x3 at +4
    for _, spec in ipairs({ { "scl20", 0x20 }, { "trn24", 0x24 } }) do
      ex[#ex + 1] = spec[1] .. "=" .. list(u32(aas + spec[2]), 16, nil, function(p)
        local b0 = u8(p); if b0 == 0xFF then return nil end
        return string.format("%d>%d:%.3f/%.3f/%.3f", b0, u8(p + 1), f32(p + 4), f32(p + 8), f32(p + 12)) end)
    end
  end
  -- live bone offsets in the model (bone table: 16 bytes, f32 x/y/z at +4)
  local model = u32(player + 0x00)
  if valid(model) then
    local bones, count = u32(model + 0x08), u8(model + 0x20)
    if valid(bones) and count > 0 and count < 64 then
      local parts = {}
      for b = 0, count - 1 do
        local q = bones + 16 * b
        parts[#parts + 1] = string.format("%.2f/%.2f/%.2f", f32(q + 4), f32(q + 8), f32(q + 12))
      end
      ex[#ex + 1] = "bones=" .. table.concat(parts, " ")
    end
  end
  -- broad-phase sphere (ledge_info +0x0..+0xC, x8) and each sphere's skip flags (+0x27: 1 map walls,
  -- 2 actor walls, 4 props, 8 actor spheres)
  if valid(ledge) then
    ex[#ex + 1] = string.format("broad=%.3f/%.3f/%.3f/%.3f", s32(ledge) / 8, s32(ledge + 4) / 8, s32(ledge + 8) / 8, s32(ledge + 12) / 8)
    local fl, n2, nd = {}, 0, u32(ledge + 0x8C)
    while valid(nd) and n2 < MAX_SPHERES do
      n2 = n2 + 1; fl[n2] = string.format("%X", u8(nd + 0x27)); nd = u32(nd + 0x28)
    end
    ex[#ex + 1] = "flags27=" .. table.concat(fl, "/")
  end
  -- portal props (object type 0x2AD): bounding sphere the broad sphere must overlap (Prop +0x28..+0x34, x8)
  -- and the gate flags func_global_asm_8066F4AC checks (+0x3D bit 2, +0x3D = seg28 +0x15 bit 1 = touch-only)
  local props, nprops = u32(0x807F6000), s32(0x80747D70)
  if valid(props) and nprops > 0 and nprops < 2000 then
    for pi = 0, nprops - 1 do
      local p = props + 0x90 * pi
      if s16(p + 0x84) == 0x2AD then
        ex[#ex + 1] = string.format("portal%d=%.3f/%.3f/%.3f/%.3f:f3C=%X:f3D=%X", pi,
          s32(p + 0x28) / 8, s32(p + 0x2C) / 8, s32(p + 0x30) / 8, s32(p + 0x34) / 8, u8(p + 0x3C), u8(p + 0x3D))
      end
    end
  end
  row = row .. "," .. table.concat(ex, "|")
  return row, { x = x, y = y, z = z, facing = facing, state = state, anim = anim_file, frame = anim_frame, spheres = spheres, changed = changed }
end

while true do
  local keys = input.get()
  if keys["L"] and not prev_keys["L"] then logging = not logging end
  prev_keys = keys

  local row, info = read_row()
  if row and logging then
    out:write(row .. "\n")
    rows = rows + 1
    if info.changed == 1 then out:flush() end
  end

  gui.text(10, 10, string.format("sphere log: %s  (%d rows)  [L to toggle]", logging and "ON" or "paused", rows))
  if info then
    gui.text(10, 26, string.format("pos %.2f %.2f %.2f  facing 0x%03X  state 0x%02X  anim 0x%X f%.1f",
      info.x, info.y, info.z, info.facing, info.state, (info.anim + 65536) % 65536, info.frame))
    local yline = 42
    for n, s in ipairs(info.spheres) do
      if s.active ~= 0 and s.r > 0 then
        gui.text(10, yline, string.format("#%d  %.2f %.2f %.2f  r %.2f", n, s.x, s.y, s.z, s.r))
        yline = yline + 16
      end
    end
  end
  emu.frameadvance()
end
