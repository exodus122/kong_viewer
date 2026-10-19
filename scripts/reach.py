"""How far each Kong's active spheres reach past its body sphere (for touching props through a
blocker, e.g. B. Locker skips).

For every animation that switches on extra spheres, every frame, and every facing angle against a
flat surface, compute:
  body  = how far sphere #1 (what holds you off the blocker) reaches toward the surface
  reach = how far the furthest active sphere reaches toward the surface
  margin = reach - body   (how far past the blocker's face the Kong can touch)
Model units, root motion included, same pose maths as index.html / func_global_asm_806195D0.
Usage: python reach.py [kong_data.js]
"""
import base64, gzip, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'kong_data.js')
D = json.loads(gzip.decompress(base64.b64decode(re.search(r'"(.*)"', open(path).read()).group(1))))

SIN = [math.sin(i * math.pi / 1024) for i in range(513)]
def half_cs(v):
    i = (v >> 6) & 0x1FF
    return (-SIN[i], SIN[512 - i]) if v & 0x8000 else (SIN[512 - i], SIN[i])

def local(a, b, c, sc, off):
    (cx, sx), (cy, sy), (cz, sz) = half_cs(a), half_cs(b), half_cs(c)
    f6, f7, f8, f9 = cx * cy, cx * sy, sx * cy, sx * sy
    w, x, y, z = f6 * cz + f9 * sz, f8 * cz - f7 * sz, f7 * cz + f8 * sz, f6 * sz - f9 * cz
    s = 2 / (w * w + x * x + y * y + z * z)
    xx, yy, zz, xy, xz, yz = x * x * s, y * y * s, z * z * s, x * y * s, x * z * s, y * z * s
    wx, wy, wz = w * x * s, w * y * s, w * z * s
    k = [(v / 32768 if v else 1) for v in sc]
    return [[(1 - (yy + zz)) * k[0], (xy + wz) * k[0], (xz - wy) * k[0], 0],
            [(xy - wz) * k[1], (1 - (xx + zz)) * k[1], (yz + wx) * k[1], 0],
            [(xz + wy) * k[2], (yz - wx) * k[2], (1 - (xx + yy)) * k[2], 0],
            [off[0], off[1], off[2], 1]]

def mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def pose(kong, an, f):
    rot, scl, root = an['rot'][f], an['scl'][f], an['root'][f]
    W = {}
    for i, b in enumerate(kong['bones']):
        c = b['chan']
        L = local(rot[3 * c], rot[3 * c + 1], rot[3 * c + 2], scl[3 * c:3 * c + 3], b['off'])
        P = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [root[0] / 32, root[1] / 32, root[2] / 32, 1]] if i == 0 else W[b['parent']]
        W[b['mtx']] = mul(L, P)
    return W

def centre(W, s):
    x, y, z = s['pos']
    if s['mtx'] < 0: return (x, y, z)
    M = W[s['mtx']]
    return tuple(x * M[0][j] + y * M[1][j] + z * M[2][j] + M[3][j] for j in range(3))

def active_set(an, f):
    for f0, f1, st in an['windows']:
        if f0 <= f <= f1: return st
    return None

sets = D['sphereSets']
ANGLES = range(-90, 91, 5)   # facing relative to the surface normal; 0 = facing it head-on
for kong in D['kongs']:
    sp = kong['collision']['spheres']
    s1 = sp[0]
    rows = []
    for an in kong['anims']:
        if all(st == 1 for _, _, st in an['windows']): continue
        best = None
        for f in range(an['frames']):
            st = active_set(an, f)
            if st is None: continue
            act = [sp[n - 1] for n in sets[st] if n - 1 < len(sp) and sp[n - 1]['r'] > 0]
            if not act: continue
            W = pose(kong, an, f)
            cs = [(centre(W, s), s['r'], s) for s in act]
            for deg in ANGLES:
                t = math.radians(deg)
                # direction toward the surface in the Kong's local frame (it faces +Z)
                n = (math.sin(t), math.cos(t))
                body = s1['r'] + s1['pos'][0] * n[0] + s1['pos'][2] * n[1]
                for (c, r, s) in cs:
                    reach = r + c[0] * n[0] + c[2] * n[1]
                    m = reach - body
                    if best is None or m > best[0]:
                        best = (m, f, deg, sp.index(s) + 1, round(c[1]), round(reach, 1), round(body, 1))
        if best and best[0] > 0:
            rows.append((round(best[0], 1), (an['names'] or ['file 0x%x' % an['anim']])[0].split(' · ')[0], hex(an['anim'])) + best[1:])
    rows.sort(reverse=True)
    print(f"\n== {kong['name']}  (body sphere #1: r {s1['r']:.0f}, forward offset {s1['pos'][2]:.1f})")
    print('  margin  animation                                file     frame  facing  sphere  centreY  reach  body')
    for m, name, a, f, deg, sn, cy, reach, body in rows[:6]:
        print(f'  {m:6.1f}  {name[:40]:40s} {a:7s}  {f:5d}  {deg:5d}°  #{sn:<5d}  {cy:6d}  {reach:6.1f} {body:6.1f}')
