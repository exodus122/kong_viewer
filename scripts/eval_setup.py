"""Replay a recorded skip setup: Kong world position + facing, attack animation, and report per frame
how close each active sphere gets to the portal touch surface (negative = overlapping = touch),
plus how deep body sphere #1 sits inside the B. Locker wedge.

  python eval_setup.py <map> <kong name> <anim file hex> <x> <y> <z> <facing u16 hex, 4096 = full turn>
"""
import math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MAP, KONG, ANIM = sys.argv[1], sys.argv[2], int(sys.argv[3], 16)
PX, PY, PZ = (float(v) for v in sys.argv[4:7])
FACE = int(sys.argv[7], 16) * 360 / 4096

os.environ['GEOM_ONLY'] = '1'
sys.argv = ['skip_search.py', MAP, '0']
src = open(os.path.join(HERE, 'skip_search.py')).read()
src = src[:src.index("if os.environ.get('GEOM_ONLY'): sys.exit()")]
exec(src)

kong = next(k for k in D['kongs'] if k['name'].lower() == KONG.lower())
an = next(a for a in kong['anims'] if a['anim'] == ANIM)
sp = kong['collision']['spheres']; s1 = sp[0]
lx, lz = to_local(PX, PZ)
yaw = FACE - bface                       # Kong facing in B. Locker local frame
print(f'\n{kong["name"]} at local ({lx:.1f}, {lz:.1f}), y {PY:.1f}, local facing {yaw % 360:.1f} deg; '
      f'anim {hex(ANIM)} {(an["names"] or ["?"])[0]}')

def tri_dist(p, t):
    # exact point-triangle distance
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

bxo, bzo = rot_y(s1['pos'][0] * SCALE, s1['pos'][2] * SCALE, yaw)
body_sd = signed_dist(np.array([[lx + bxo, lz + bzo]]))[0] - s1['r'] * SCALE
print(f'body sphere #1: {"inside" if body_sd < 0 else "clear of"} the wedge by {abs(body_sd):.2f}')
best = None
for fr in range(an['frames']):
    st = active_set(an, fr)
    Wm = pose_s(kong, an, fr)
    row = []
    for k in SETS[st] if st is not None else []:
        s = sp[k - 1]
        if s['r'] <= 0: continue
        c = centre(Wm, s)
        ox, oz = rot_y(c[0] * SCALE, c[2] * SCALE, yaw)
        p = np.array([lx + ox, PY + c[1] * SCALE, lz + oz])
        d = min(tri_dist(p, t) for t in ptris) - s['r'] * SCALE
        row.append(f'#{k}:{d:6.1f}')
        if best is None or d < best[0]: best = (d, fr, k)
    print(f'  frame {fr:3d} set {st}: ' + '  '.join(row))
print(f'closest: {best[0]:.2f} units (frame {best[1]}, sphere #{best[2]}); negative means it touches')
