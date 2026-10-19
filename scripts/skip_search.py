"""Search B. Locker skip setups: Kong position, facing and attack frame where an active attack sphere
touches the portal's touch triangles while body sphere #1 stays outside the B. Locker's blocker wedge.

Geometry is worked out in the B. Locker's local frame (world units): it faces +z (toward the player),
its wedge footprint comes from the actor-wall triangles of model 0x65, and the portal touch
triangles (prop wall flag 0x02) are transformed in from the lobby setup. Kongs are posed with the same
maths as the viewer (func_global_asm_806195D0), at player scale 0.15.

  python skip_search.py [map index (default 0xA9 Japes lobby)] [penetration allowance, default 0]

The penetration allowance lets body sphere #1 sink into the wedge by that many world units
(DK measured about 2.8 in the Japes lobby, since the blocking only stops movement after contact).
"""
import math, os, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ptr

MAP = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0xA9
SINK = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
SCALE = 0.15

# pose helpers shared with reach.py
_src = open(os.path.join(HERE, 'reach.py')).read()
sys.argv = [sys.argv[0]]
exec(_src[:_src.index('sets = D[')])
SETS = D['sphereSets']

# runtime bone-scale overrides (Lanky's arm stretch), measured from sphere_logger.lua logs
import stretch as _stretch
STRETCH = _stretch.stretch_table()
def pose_s(kong, an, f):
    ov = _stretch.overrides_at(STRETCH, an['anim'], f)
    if not ov: return pose(kong, an, f)
    rot, scl, root = an['rot'][f], an['scl'][f], an['root'][f]
    W = {}
    for i, b in enumerate(kong['bones']):
        c = b['chan']
        L = local(rot[3 * c], rot[3 * c + 1], rot[3 * c + 2], scl[3 * c:3 * c + 3], b['off'])
        for ba, bb, sv in ov:
            if b['mtx'] == ba: L = [[v * sv[k] for v in L[k][:3]] + [0] for k in range(3)] + [L[3]]
            if b['mtx'] == bb: L = [[v / sv[k] for v in L[k][:3]] + [0] for k in range(3)] + [L[3]]
        P = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [root[0] / 32, root[1] / 32, root[2] / 32, 1]] if i == 0 else W[b['parent']]
        W[b['mtx']] = mul(L, P)
    return W

def rot_y(x, z, deg):
    t = math.radians(deg)
    return x * math.cos(t) + z * math.sin(t), -x * math.sin(t) + z * math.cos(t)

# ---------------------------------------------------------------- lobby setup
setup = ptr.get_file(9, MAP)
n = struct.unpack_from('>I', setup, 0)[0]
props = [(struct.unpack_from('>h', setup, 4 + 0x30 * i + 0x28)[0],) + struct.unpack_from('>4f', setup, 4 + 0x30 * i)
         + (struct.unpack_from('>f', setup, 4 + 0x30 * i + 0x1C)[0],) for i in range(n)]
o = 4 + 0x30 * n
o += 4 + 0x24 * struct.unpack_from('>I', setup, o)[0]
na = struct.unpack_from('>I', setup, o)[0]; o += 4
blocker = None
for i in range(na):
    x, y, z, sc = struct.unpack_from('>4f', setup, o)
    face, typ = struct.unpack_from('>HH', setup, o + 0x30)
    if typ + 0x10 == 0x8A: blocker = (x, y, z, sc, face * 360 / 4096)
    o += 0x38
bx, by, bz, bsc, bface = blocker
bs = SCALE * bsc

def to_local(wx, wz):           # world -> B. Locker local (x, z)
    return rot_y(wx - bx, wz - bz, -bface)

# wedge footprint (convex) from the actor-wall triangles, bottom vertices
f = ptr.get_file(5, 0x65 - 1)
base = struct.unpack_from('>I', f, 0)[0]; rel = lambda p: p - base + 0x28
q = rel(struct.unpack_from('>I', f, 0xC)[0]) + 8
q += 4 + 0x14 * struct.unpack_from('>I', f, q)[0]
q += 4 + 0x10 * struct.unpack_from('>I', f, q)[0]
nt = struct.unpack_from('>I', f, q)[0]; q += 4
foot = set()
for i in range(nt):
    v = struct.unpack_from('>9f', f, q + 0x2C * i)
    for k in range(3):
        foot.add((round(v[3 * k] * bs, 3), round(v[3 * k + 2] * bs, 3)))
pts = np.array(sorted(foot))
# convex hull (monotone chain)
def hull(p):
    p = sorted(map(tuple, p))
    def half(seq):
        h = []
        for pt in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (pt[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (pt[0] - h[-2][0]) <= 0: h.pop()
            h.append(pt)
        return h
    lo, up = half(p), half(reversed(p))
    return np.array(lo[:-1] + up[:-1])
W = hull(pts)

def signed_dist(P):            # P: (N,2) -> signed distance to convex polygon W (negative inside)
    n = len(W); d_out = np.full(len(P), np.inf); inside = np.ones(len(P), bool); d_in = np.full(len(P), np.inf)
    for i in range(n):
        a, b = W[i], W[(i + 1) % n]
        e = b - a; L = np.hypot(*e); nrm = np.array([e[1], -e[0]]) / L   # outward for CCW
        s = (P - a) @ nrm
        inside &= s <= 0
        d_in = np.minimum(d_in, -s)
        t = np.clip(((P - a) @ e) / (L * L), 0, 1)
        proj = a + t[:, None] * e
        d_out = np.minimum(d_out, np.hypot(*(P - proj).T))
    return np.where(inside, -d_in, d_out)

# portal touch triangles -> local, sampled densely
surf = []
for typ, px, py, pz, psc, pry in props:
    try: pf = ptr.get_file(4, typ)
    except Exception: continue
    if len(pf) < 0x50: continue
    wo = struct.unpack_from('>I', pf, 0x4C)[0]
    if not (0 < wo < len(pf) - 4): continue
    cnt = struct.unpack_from('>i', pf, wo)[0]
    if not (0 < cnt < 2000): continue
    tris = []
    for k in range(cnt):
        qq = wo + 4 + 0x16 * k
        if pf[qq + 18] & 2:
            v = struct.unpack_from('>9h', pf, qq)
            tri = []
            for j in range(3):
                wx, wz = rot_y(v[3 * j] * psc, v[3 * j + 2] * psc, pry)
                lx, lz = to_local(px + wx, pz + wz)
                tri.append((lx, py + v[3 * j + 1] * psc, lz))
            tris.append(np.array(tri))
    if tris and abs(np.mean([t[:, 2].mean() for t in tris])) < 120:
        surf.append((typ, tris))
assert surf, 'no portal touch surface near the B. Locker'
# the lobby portal is prop 0x2AD; otherwise take the touch surface closest to the B. Locker
# (Caves also has prop 0x1FE with touch triangles 250 units to the side, listed first)
def _closeness(entry):
    typ, tris = entry
    c = np.mean([t.mean(0) for t in tris], 0)
    return (typ != 0x2AD, math.hypot(c[0], c[2]))
ptyp, ptris = min(surf, key=_closeness)
S = []
for t in ptris:
    for u in np.linspace(0, 1, 40):
        for v in np.linspace(0, 1 - u, max(2, int(40 * (1 - u)))):
            S.append(t[0] + u * (t[1] - t[0]) + v * (t[2] - t[0]))
S = np.array(S)   # (N,3) local x, y, z
floor_y = by

print(f'map 0x{MAP:x}: B. Locker at ({bx:.1f}, {bz:.1f}) facing {bface:.1f}, wedge scale {bs:.3f}')
print('wedge footprint (B. Locker local, +z toward player):', [tuple(np.round(p, 1)) for p in W])
print(f'portal prop 0x{ptyp:x} touch surface: x {S[:,0].min():.1f}..{S[:,0].max():.1f}, '
      f'y {S[:,1].min():.0f}..{S[:,1].max():.0f}, z {S[:,2].min():.1f}..{S[:,2].max():.1f}')
print('(player-side right = +x when facing the B. Locker)')
_zp = S[:, 2].mean(); _xr = S[:, 0].max(); _xl = S[:, 0].min()
def _side_x(z, sign):
    # wedge boundary x at depth z on one side (walk the hull edges)
    xs = []
    for i in range(len(W)):
        a, b2 = W[i], W[(i + 1) % len(W)]
        if (a[1] - z) * (b2[1] - z) <= 0 and a[1] != b2[1]:
            xs.append(a[0] + (z - a[1]) * (b2[0] - a[0]) / (b2[1] - a[1]))
    if not xs: return float("nan")
    return max(xs) if sign > 0 else min(xs)
print(f'gap at portal depth: right side {_side_x(_zp, 1) - _xr:.1f}, left side {_xl - _side_x(_zp, -1):.1f} (wedge side to portal edge, world units)')
if os.environ.get('GEOM_ONLY'): sys.exit()

# ---------------------------------------------------------------- search
for kong in D['kongs']:
    sp = kong['collision']['spheres']; s1 = sp[0]
    best = []
    for an in kong['anims']:
        if all(st == 1 for _, _, st in an['windows']): continue
        name = (an['names'] or ['file 0x%x' % an['anim']])[0].split(' · ')[0]
        for fr in range(an['frames']):
            st = active_set(an, fr)
            if st is None: continue
            act = [sp[k - 1] for k in SETS[st] if k - 1 < len(sp) and sp[k - 1]['r'] > 0 and sp[k - 1]['mtx'] >= 0]
            if not act: continue
            Wm = pose_s(kong, an, fr)
            for s in act:
                c = centre(Wm, s)
                r = s['r'] * SCALE
                for deg in range(0, 360, 5):
                    # Kong local -> B. Locker local
                    ox, oz = rot_y(c[0] * SCALE, c[2] * SCALE, deg)
                    bxo, bzo = rot_y(s1['pos'][0] * SCALE, s1['pos'][2] * SCALE, deg)
                    oy = floor_y + c[1] * SCALE
                    # for each surface point, how far the attack centre must sit from it so the body sphere is clear
                    body_at = S[:, [0, 2]] - np.array([ox, oz]) + np.array([bxo, bzo])
                    need = np.maximum(0, s1['r'] * SCALE - SINK - signed_dist(body_at))
                    dist = np.sqrt(need ** 2 + (S[:, 1] - oy) ** 2)
                    k = int(np.argmin(dist))
                    m = r - dist[k]
                    if m > -3:
                        kc = S[k, [0, 2]] - np.array([ox, oz])
                        best.append((round(m, 2), name, hex(an['anim']), fr, deg, sp.index(s) + 1, tuple(np.round(kc, 1))))
    best.sort(reverse=True)
    print(f"\n== {kong['name']}")
    if not best:
        print('   no setup within 3 units of touching')
        continue
    seen = set()
    for m, name, a, fr, deg, sn, kc in best:
        key = (a, sn)
        if key in seen: continue
        seen.add(key)
        side = 'right' if kc[0] > 0 else 'left'
        print(f'   {"TOUCH" if m >= 0 else "miss "} margin {m:6.2f}  {name[:32]:32s} {a:7s} frame {fr:3d}  sphere #{sn:<2d} '
              f'Kong at local ({kc[0]:6.1f}, {kc[1]:6.1f}) [{side} side]  facing {deg:3d}°')
        if len(seen) >= 5: break
