"""World-space geometry of a lobby's B. Locker blocker and portal touch surface.

  B. Locker = actor 0x8A ("Banana sign" in D_global_asm_8074E8B0), model 0x65. Its blocker is the
              model's actor-wall triangle list (collision table, 0x2C records), scaled by
              0.15 * setup scale and rotated by the setup facing (u16 at +0x30, 4096 = full turn).
  Portal    = the prop whose wall triangles have flag 0x02 ("touch", func_global_asm_8066CEE4);
              prop setup: f32 x,y,z, scale at +0xC, rotation in degrees at +0x18/+0x1C/+0x20, type at +0x28.
Usage: python lobby_geom.py [map index, default 0xA9 = Japes lobby]
"""
import math, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptr

MAP = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0xA9
PLAYER_SCALE = 0.15          # extra_player_info->unk1D0 (code_CC800.c), func_global_asm_806134B4 default

def rot_y(x, z, deg):
    t = math.radians(deg)
    return x * math.cos(t) + z * math.sin(t), -x * math.sin(t) + z * math.cos(t)

setup = ptr.get_file(9, MAP)
n = struct.unpack_from('>I', setup, 0)[0]
props = []
for i in range(n):
    o = 4 + 0x30 * i
    x, y, z, sc = struct.unpack_from('>4f', setup, o)
    ry = struct.unpack_from('>f', setup, o + 0x1C)[0]
    typ = struct.unpack_from('>h', setup, o + 0x28)[0]
    props.append((typ, x, y, z, sc, ry))
o = 4 + 0x30 * n
m = struct.unpack_from('>I', setup, o)[0]; o += 4 + 0x24 * m
na = struct.unpack_from('>I', setup, o)[0]; o += 4
actors = []
for i in range(na):
    x, y, z, sc = struct.unpack_from('>4f', setup, o)
    face, typ = struct.unpack_from('>HH', setup, o + 0x30)
    actors.append((typ + 0x10, x, y, z, sc, face * 360 / 4096))
    o += 0x38

# portal: props with touch-flagged wall triangles
portals = []
for typ, x, y, z, sc, ry in props:
    try: f = ptr.get_file(4, typ)
    except Exception: continue
    if len(f) < 0x50: continue
    wo = struct.unpack_from('>I', f, 0x4C)[0]
    if not (0 < wo < len(f) - 4): continue
    cnt = struct.unpack_from('>i', f, wo)[0]
    if not (0 < cnt < 2000): continue
    touch = []
    for k in range(cnt):
        q = wo + 4 + 0x16 * k
        v = struct.unpack_from('>9h', f, q)
        if f[q + 18] & 2: touch.append(v)
    if touch: portals.append((typ, x, y, z, sc, ry, touch))

def blocker_tris(model):
    f = ptr.get_file(5, model - 1)
    base = struct.unpack_from('>I', f, 0)[0]; rel = lambda p: p - base + 0x28
    o = rel(struct.unpack_from('>I', f, 0xC)[0]) + 8
    ns = struct.unpack_from('>I', f, o)[0]; o += 4 + 0x14 * ns
    npt = struct.unpack_from('>I', f, o)[0]; o += 4 + 0x10 * npt
    nt = struct.unpack_from('>I', f, o)[0]; o += 4
    return [struct.unpack_from('>9f', f, o + 0x2C * i) for i in range(nt)]

print(f'map 0x{MAP:x}')
for typ, ax, ay, az, asc, aface in actors:
    if typ != 0x8A: continue
    s = PLAYER_SCALE * asc
    tris = blocker_tris(0x65)
    pts = []
    for t in tris:
        for k in range(3):
            lx, ly, lz = t[3 * k:3 * k + 3]
            wx, wz = rot_y(lx * s, lz * s, aface)
            pts.append((ax + wx, ay + ly * s, az + wz))
    fwd = rot_y(0, 1, aface)
    print(f'B. Locker at ({ax:.1f}, {ay:.1f}, {az:.1f}) facing {aface:.1f} deg, scale {s:.3f}')
    # front face = local z 110 (most forward plane)
    fx, fz = rot_y(0, 110 * s, aface)
    face_d = 110 * s
    print(f'  blocker front face: {face_d:.1f} units in front of its origin, '
          f'{(max(t[0] for t in tris) - min(t[0] for t in tris)) * s:.0f} wide, '
          f'up to {max(t[1] for t in tris) * s:.0f} high')
    for ptyp, px, py, pz, psc, pry, touch in portals:
        # signed distance of the portal touch plane from the blocker front face, along the blocker's facing
        tz = touch[0][2] * psc            # vertex 0 z (touch tris are a flat plane)
        wx, wz = rot_y(0, tz, pry)
        plane = (px + wx, pz + wz)
        rel_portal = (plane[0] - ax) * fwd[0] + (plane[1] - az) * fwd[1]
        gap = face_d - rel_portal
        print(f'  touch prop 0x{ptyp:x} at ({px:.0f}, {py:.0f}, {pz:.0f}) rot {pry:.0f}: touch plane is '
              f'{gap:.1f} units behind the blocker face ({gap / PLAYER_SCALE:.0f} Kong model units)')
