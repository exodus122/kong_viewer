# Kong collision sphere viewer

A 3D viewer for the five Kongs' collision spheres, posed by their real animations.
All data is decoded from your own US ROM. Nothing from the game ships with the viewer.

```
python scripts/extract.py                        # writes kong_data.js (~2 MB); ROM: the decomp's baserom.us.z64 or --rom
python -m http.server 8764                       # then open http://localhost:8764
```

Opening `index.html` straight from disk also works, since it loads `kong_data.js` with a
plain script tag. You can also drop a `kong_data.js` file onto the page.

## What it shows

- **Bone spheres**: `LedgeInfo8C` nodes. These are the spheres the wall engine tests
  (`func_global_asm_806734E4` in `src/global_asm/code_77B90.s`). Each one is attached to a bone
  matrix and moves with the animation.
- **Body spheres**: the same list, but with matrix −1. They sit on the actor's root matrix
  (`ledgeInfo->unk70`), so animation doesn't move them.
- **Broad-phase sphere**: `LedgeInfo.unkC`, centred on the actor. The narrow phase only runs
  when this sphere touches a wall (`func_global_asm_806730A4`).
- **Trails**: each sphere's path over the whole animation. The "Travel" column gives the path
  length in model units.

Everything is in model units. Multiply by the actor's scale to get world units.

## Active spheres

Each frame the player's sphere list is reset by `func_global_asm_80675EE0`: it finds the first entry in
`D_global_asm_80748FE8` (12 bytes each: animation file, first/last frame, damage, set, flags) that
matches the current animation file and frame. Then `func_global_asm_8067605C` turns every sphere off
and turns on that set from `D_global_asm_80748E50` (29 lists of 1-based sphere numbers). If no entry
matches, the previous set stays active. For almost every animation that set is just sphere #1 (a
body sphere). Swimming, bouncing, ledge pull-ups, attacks and minecarts use other sets. A few use
set 0, which has no spheres. `D_global_asm_80748F58` gives some attack spheres an interaction mask.
The extractor reads these tables from the compressed global_asm .data (ROM 0xC29D4, vram base 0x80744460).
In the viewer, "Spheres: active this frame" shows only the current set, and the HUD names it.

## Formats (reverse engineered from the decomp)

| Data | Where | Notes |
|---|---|---|
| Pointer tables | `getPointerTableFile`, `func_global_asm_8066B4D4` | ROM base `0x101C50`; bit 31 marks a redirect; gzip per `D_global_asm_80748E18` |
| Actor model header | `ActorModelHeader`, `func_global_asm_80612E90` | pointers relocate as `p - header[0] + 0x28` |
| Bones (16 B each) | header `+0x08` | `u8 parent, u8 matrix, u8 anim channel, pad, f32 x,y,z` |
| Collision table | header `+0x0C`, `func_global_asm_8066E2C0` | `f32 broad, f32 ?, n × {f32 x,y,z,r; s32 matrix*64 or −1}`, then point and triangle lists |
| Sphere transform | `func_global_asm_80671880` | `(x,y,z,1) · bone matrix`, radius × scale |
| Mesh | F3DEX2 display lists | segment 3 = model data, segment 4 = bone matrices; `G_DL` branches to segments 7/8 switch hand geometry (`func_global_asm_8061324C`) |
| Textures | pointer table 25, RGBA16 | each triangle's texture comes from the tile `G_TEXTURE` selects, the TMEM address it reads and the image last loaded there (as 3d_model_viewer's DK64 actor renderer); `G_SETTIMG` is a table-25 id (segment 0) or a segment from the model's animated-texture list (header +0x10: eyes, mouths; first frame); textures loaded by a `G_LOADBLOCK` with dxt 0 are stored with odd rows' 32-bit words swapped |
| Animation file (table 11) | `func_global_asm_80619C2C` | header: `f32 speed, s16 flags, s16 data offset (+6), s16 root xyz, u8 root bits xyz, u8 channels+1, u8 frames, u8 bytes per frame`, then one u16 descriptor per component (`base & 0xFFF0`, bit count in the low nibble, `0x10` = a scale value follows); per-frame records are MSB-first bitstreams |
| Bone matrices | `func_global_asm_806195D0` (`code_1E2D0.s`) | euler (u16 = full turn) → quaternion `qz·qy·qx` → row-vector matrix, rows scaled by `scale/0x8000`, translation = bone offset, chained `local · parent`; root offset = raw / 32 |
| Animation scripts (table 13) | handlers at `D_global_asm_80746BEC` | opcodes 0x14/0x15/0x17/0x4F take a file index; 0x18/0x19/0x1A/0x50 take a generic id, remapped per actor through `D_global_asm_807FBB58[id*7 + type−2]` |

Kong models: DK = 4, Diddy = 1, Lanky = 6, Tiny = 9, Chunky = 12 (actor geometry index, 1-based).

## Animation names

Labels come from the game code, not from file numbers. The player code sets
`Actor.control_state` and then calls `playAnimation(actor, type)`. The anim-type table says which
script each Kong runs for that type, and the script plays the animation file(s).
`action_types.py` scans the decomp's C and assembly for those (state, type) pairs and writes
`action_types.json`. The state names (`control_states.txt`) come from
[ScriptHawk](https://github.com/Isotarge/ScriptHawk) (`games/dk64.lua`). When a type's script
plays several files, each one is labelled "part n/m".

ScriptHawk's own per-animation list (`names_raw.txt`) only matches DK's file indices below 0x3E.
Above that it drifts: its "Rolling" is really DK's gun idle. So that list is only a fallback for
those low indices, carried to the other Kongs through the generic-id table. Anything
neither source covers shows its file index.

## Files

- `index.html`: the viewer (three.js 0.160 from jsDelivr); `kong_data.js`: its data, written by `scripts/extract.py`
- `scripts/`
  - `extract.py`: the extractor; `ptr.py`: pointer-table access
  - `opcodes.py` → `opcodes.json`: argument length of each animation-script opcode, regenerated from the decomp sources
  - `action_types.py` → `action_types.json`: anim type → control states, scanned from the decomp
  - `control_states.txt`, `names_raw.txt`: names from ScriptHawk
  - `gamepose.py`, `reach.py`, `stretch.py`: game-accurate posing (sampled frames, Lanky's logged arm stretch)
  - `skip_search.py`, `skip_search2.py`, `lobby_geom.py`, `lobby_walls.py`, `eval_setup.py`: B. Locker skip search
    (`python scripts/skip_search2.py <map> [kong|all] [sink] [lag boost]`, `TOP=n` lists the best updates)
  - `check_portal.py`, `compare_log.py`, `compare_log2.py`: checks against BizHawk logs
- `bizhawk/`: Lua scripts for BizHawk
  - `sphere_logger.lua`: logs position, animation and every collision sphere each frame to `results/logs/`
  - `dk64_watch.lua`: pointer watches (position, angle, speeds, animation, broad phase)
  - `last_sphere_test.lua`: the experiment that showed only the last tested sphere can touch the portal
- `results/logs/`: the BizHawk logs (`kong_spheres_<date>.csv`; Lanky's arm stretch is read from these)
- `results/skip/`: search output per lobby (`skip_<map>.png` top-down pictures, older `<map>.txt` results)
