"""Check the portal touch geometry against logged in-game spheres on the frame the touch registered.
At least one active sphere must overlap a touch triangle for the touch to fire.

  python check_portal.py <log.csv> <map index>
"""
import csv, math, struct, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptr

log, MAP = sys.argv[1], int(sys.argv[2], 0)

def rot_y(x, z, deg):
    t = math.radians(deg)
    return x * math.cos(t) + z * math.sin(t), -x * math.sin(t) + z * math.cos(t)

def tri_dist(p, t):
    a, b, c = t
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = ab @ ap, ac @ ap
    if d1 <= 0 and d2 <= 0: return np.linalg.norm(p - a)
    bp = p - b; d3, d4 = ab @ bp, ac @ bp
    if d3 >= 0 and d4 <= d3: return np.linalg.norm(p - b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0: return np.linalg.norm(p - (a + d1 / (d1 - d3) * ab))
    cp = p - c; d5, d6 = ab @ cp, ac @ cp
    if d6 >= 0 and d5 <= d6: return np.linalg.norm(p - c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0: return np.linalg.norm(p - (a + d2 / (d2 - d6) * ac))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        return np.linalg.norm(p - (b + (d4 - d3) / ((d4 - d3) + (d5 - d6)) * (c - b)))
    n = np.cross(ab, ac); return abs((p - a) @ n) / np.linalg.norm(n)

setup = ptr.get_file(9, MAP)
n = struct.unpack_from('>I', setup, 0)[0]
portal = None
for i in range(n):
    o = 4 + 0x30 * i
    typ = struct.unpack_from('>h', setup, o + 0x28)[0]
    if typ == 0x2AD:
        x, y, z, sc = struct.unpack_from('>4f', setup, o)
        rx, ry, rz = struct.unpack_from('>3f', setup, o + 0x18)
        portal = (x, y, z, sc, rx, ry, rz)
pf = ptr.get_file(4, 0x2AD)
wo = struct.unpack_from('>I', pf, 0x4C)[0]; cnt = struct.unpack_from('>i', pf, wo)[0]
local_tris = []
for k in range(cnt):
    q = wo + 4 + 0x16 * k
    if pf[q + 18] & 2: local_tris.append(np.array(struct.unpack_from('>9h', pf, q), float).reshape(3, 3))
print('portal setup: pos (%.1f, %.1f, %.1f) scale %.3f rot (%.1f, %.1f, %.1f)' % portal)
print('prop file header floats:', [round(v, 3) for v in struct.unpack_from('>4f', pf, 0x0)], 'unk20:', struct.unpack_from('>f', pf, 0x20)[0])

def world_tris(scale, sign=1):
    px, py, pz, sc, rx, ry, rz = portal
    out = []
    for t in local_tris:
        w = []
        for v in t:
            x, y, z = v * scale
            wx, wz = rot_y(x, z, sign * ry)
            w.append((px + wx, py + y, pz + wz))
        out.append(np.array(w))
    return out

rows = [r for r in csv.DictReader(open(log))]
touch = next(i for i, r in enumerate(rows) if r['control_state'] == '0x87')
for r in rows[touch - 4:touch + 1]:
    sph = []
    for k in range(1, 17):
        if r.get(f's{k}_active') == '1' and r[f's{k}_r'] and float(r[f's{k}_r']) > 0:
            sph.append((k, np.array([float(r[f's{k}_{c}']) for c in 'xyz']), float(r[f's{k}_r'])))
    print(f"\nemu frame {r['emu_frame']} state {r['control_state']} anim {r['anim_file']} f{r['anim_frame']} lagged {r['lagged']}")
    for label, scale, sign in [('setup scale', portal[3], 1), ('mirrored rotation', portal[3], -1),
                               ('scale x0.5', portal[3] * 0.5, 1), ('scale x1.5', portal[3] * 1.5, 1), ('scale x2', portal[3] * 2, 1)]:
        T = world_tris(scale, sign)
        best = min((min(tri_dist(p, t) for t in T) - rad, k) for k, p, rad in sph) if sph else None
        print(f'   {label:18s} closest sphere gap: {best[0]:7.2f} (sphere #{best[1]})' if best else '   no active spheres')
