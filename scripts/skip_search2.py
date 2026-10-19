"""B. Locker skip search with lobby walls.

Finds, per Kong, the attack / frame / facing / standing spot where an active attack sphere overlaps
the portal touch triangles while body sphere #1 stands somewhere reachable: outside the B. Locker
wedge and the lobby walls (map walls sliced at body-sphere height), connected to the area in
front of the B. Locker. Lanky's arm stretch comes from logged data (stretch.py).

  python skip_search2.py <map> [kong name or all] [sink, world units the body may sink into walls]
Writes results/skip/skip_<map>.png (top-down).
"""
import math, os, sys
import numpy as np
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = sys.argv[1]
ARGMAP = int(MAP, 0)
WHO = sys.argv[2].lower() if len(sys.argv) > 2 else 'all'
SINK = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6   # measured: DK walk-up sank 0.6 units
BOOST = int(sys.argv[4]) if len(sys.argv) > 4 else 2      # lag boost: 2 = no lag (D_global_asm_80744478)

# geometry + pose helpers from skip_search.py (stops before its own search)
os.environ['GEOM_ONLY'] = '1'
sys.argv = ['skip_search.py', MAP, str(SINK)]
_src = open(os.path.join(HERE, 'skip_search.py')).read()
_src = _src[:_src.index("if os.environ.get('GEOM_ONLY'): sys.exit()")]
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    exec(_src)
from lobby_walls import load_walls
import gamepose

floor = float(S[:, 1].min())                 # the portal stands on the floor
MAP = hex(ARGMAP)

# ---------------------------------------------------------------- walls at a given height -> 2D segments
walls_local = []
for v, *_ in load_walls(ARGMAP):
    pts = []
    for k in range(3):
        lx_, lz_ = to_local(v[3 * k], v[3 * k + 2])
        pts.append((lx_, v[3 * k + 1], lz_))
    P = np.array(pts)
    if np.hypot(P[:, 0], P[:, 2]).min() < 260: walls_local.append(P)

def slice_walls(h):
    segs = []
    for P in walls_local:
        ylo, yhi = P[:, 1].min(), P[:, 1].max()
        if not (ylo - 2 < h < yhi + 10): continue          # func_global_asm_80673240 height test
        hh = min(max(h, ylo + 1e-3), yhi - 1e-3) if yhi - ylo > 2e-3 else ylo
        cut = []
        for i in range(3):
            a, b = P[i], P[(i + 1) % 3]
            if (a[1] - hh) * (b[1] - hh) <= 0 and a[1] != b[1]:
                t = (hh - a[1]) / (b[1] - a[1]); cut.append((a[0] + t * (b[0] - a[0]), a[2] + t * (b[2] - a[2])))
        if len(cut) >= 2: segs.append((cut[0], cut[1]))
        elif yhi - ylo < 2e-3:                               # flat triangle: use its edges
            for i in range(3): segs.append(((P[i][0], P[i][2]), (P[(i + 1) % 3][0], P[(i + 1) % 3][2])))
    return segs

def seg_dist(Q, segs):
    d = np.full(len(Q), np.inf)
    for (ax, az), (bx_, bz_) in segs:
        e = np.array([bx_ - ax, bz_ - az]); L2 = e @ e
        if L2 < 1e-9: continue
        t = np.clip(((Q - [ax, az]) @ e) / L2, 0, 1)
        d = np.minimum(d, np.hypot(*(Q - ([ax, az] + t[:, None] * e)).T))
    return d

# ---------------------------------------------------------------- reachable body-centre grid
STEP = 0.5
GX = np.arange(-180, 180, STEP); GZ = np.arange(-180, 140, STEP)
def reachable_grid(r_body, h):
    XX, ZZ = np.meshgrid(GX, GZ, indexing='ij')
    Q = np.stack([XX.ravel(), ZZ.ravel()], 1)
    free = (signed_dist(Q) >= r_body - SINK) & (seg_dist(Q, slice_walls(h)) >= r_body - SINK)
    free = free.reshape(XX.shape)
    # flood fill from just in front of the B. Locker
    start = (np.searchsorted(GX, 0.0), np.searchsorted(GZ, W[:, 1].max() + r_body + 4))
    seen = np.zeros_like(free); dq = deque()
    if free[start]: seen[start] = True; dq.append(start)
    while dq:
        i, j = dq.popleft()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a2, b2 = i + di, j + dj
            if 0 <= a2 < free.shape[0] and 0 <= b2 < free.shape[1] and free[a2, b2] and not seen[a2, b2]:
                seen[a2, b2] = True; dq.append((a2, b2))
    return seen

def lookup(grid, P):
    i = np.round((P[:, 0] - GX[0]) / STEP).astype(int); j = np.round((P[:, 1] - GZ[0]) / STEP).astype(int)
    ok = (i >= 0) & (i < len(GX)) & (j >= 0) & (j < len(GZ))
    out = np.zeros(len(P), bool); out[ok] = grid[i[ok], j[ok]]
    return out

# portal surface samples (coarser) and approach offsets
Ssub = S[::max(1, len(S) // 1500)]
ang = np.linspace(0, 2 * np.pi, 12, endpoint=False)

results = {}
PERUPD = {}   # best margin per (animation, frame), printed with TOP=n
for kong in D['kongs']:
    if WHO != 'all' and kong['name'].lower() != WHO: continue
    sp = kong['collision']['spheres']; s1 = sp[0]
    # Kong centre may sit (radius - horizontal forward offset) from walls: approach with the offset pointing
    # away, then turn in place (turning is not pushed back out; DK's Aztec log shows exactly this)
    rb = s1['r'] * SCALE - math.hypot(s1['pos'][0], s1['pos'][2]) * SCALE
    h = floor + s1['pos'][1] * SCALE
    grid = reachable_grid(rb, h)
    best = None
    for an in kong['anims']:
        if all(st == 1 for _, _, st in an['windows']): continue
        name = (an['names'] or ['file 0x%x' % an['anim']])[0].split(' · ')[0]
        # only the frames the game actually evaluates (gamepose.py): spheres from the previous update's pose
        for fr, pose_fr, act_all, Wm in gamepose.collision_states(kong, an, BOOST):
            # Only the LAST tested sphere can register the touch: func_global_asm_80673708 clears the touch
            # value (D_global_asm_807FB601) for every sphere it tests, and func_global_asm_8066F4AC reads it
            # after the loop (confirmed on every logged overlap: Lanky's #7 overlaps never touch, Diddy's #11 neither)
            act = [act_all[-1]] if act_all and act_all[-1]['mtx'] >= 0 else []
            if not act: continue
            cs = [(centre(Wm, s), s) for s in act]
            for deg in range(0, 360, 5):
                bxo, bzo = rot_y(s1['pos'][0] * SCALE, s1['pos'][2] * SCALE, deg)
                for c, s in cs:
                    r = s['r'] * SCALE
                    ox, oz = rot_y(c[0] * SCALE, c[2] * SCALE, deg)
                    qy = floor + c[1] * SCALE
                    dy = Ssub[:, 1] - qy
                    for rad in (0.0, 0.5 * r, 0.9 * r):
                        offs = [(0.0, 0.0)] if rad == 0 else [(rad * math.cos(t), rad * math.sin(t)) for t in ang]
                        for dx, dz in offs:
                            body = Ssub[:, [0, 2]] + [dx - ox, dz - oz]          # Kong centre
                            ok = lookup(grid, body)
                            if not ok.any(): continue
                            m = r - np.sqrt(rad * rad + dy[ok] ** 2)
                            k = int(np.argmax(m))
                            key = (an['anim'], fr)
                            if m[k] > PERUPD.setdefault(kong['name'], {}).get(key, -1e9): PERUPD[kong['name']][key] = float(m[k])
                            if best is None or m[k] > best[0]:
                                kc = body[ok][k]
                                best = (float(m[k]), name, an['anim'], fr, deg, sp.index(s) + 1, kc)
    results[kong['name']] = best

print(f'map {MAP}: B. Locker ({bx:.1f}, {bz:.1f}) facing {bface:.1f}; floor y {floor:.1f}; sink {SINK}; lag boost {BOOST}')
for name, best in results.items():
    if best is None:
        print(f'  {name:7s} no reachable setup'); continue
    m, an_name, a, fr, deg, sn, kc = best
    wx, wz = rot_y(kc[0], kc[1], bface); wx += bx; wz += bz
    face = ((deg + bface) % 360) * 4096 / 360
    side = 'right' if kc[0] > 0 else 'left'
    print(f'  {name:7s} {"TOUCH" if m >= 0 else "miss "} margin {m:5.2f}  {an_name} (0x{a:x}) frame {fr:.2f}, sphere #{sn}; '
          f'stand at world ({wx:.1f}, {wz:.1f}) [{side} side], facing 0x{int(face) & 0xFFF:03X} ({(deg + bface) % 360:.0f} deg)')

if os.environ.get('TOP'):
    for name, d in PERUPD.items():
        for (a, fr), m in sorted(d.items(), key=lambda kv: -kv[1])[:int(os.environ['TOP'])]:
            an = next(x for x in D['kongs'] if x['name'] == name)['anims']
            an = next(x for x in an if x['anim'] == a)
            upd = 1 + round((fr - gamepose.step_per_update(an, BOOST) / 2) / gamepose.step_per_update(an, BOOST))
            print(f'    {name:7s} 0x{a:x} update {upd:2d} (frame {fr:5.2f}): margin {m:6.2f}')

# ---------------------------------------------------------------- picture
try:
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 7))
    for (a1, b1) in slice_walls(floor + 10):
        ax.plot([a1[0], b1[0]], [a1[1], b1[1]], c='#888', lw=1)
    ax.fill(*np.vstack([W, W[:1]]).T, color='#d9534f', alpha=0.25, label='B. Locker wedge')
    ax.plot(S[:, 0], S[:, 2], '.', ms=1, c='#7b3fe4', label='portal touch surface')
    colors = {'DK': '#f2c14e', 'Diddy': '#e5484d', 'Lanky': '#3e8ef7', 'Tiny': '#a06cd5', 'Chunky': '#3fb950'}
    for name, best in results.items():
        if best and best[0] >= 0:
            kc = best[6]; ax.add_patch(plt.Circle(kc, SCALE * D['kongs'][[k['name'] for k in D['kongs']].index(name)]['collision']['spheres'][0]['r'],
                                                  fill=False, color=colors[name], lw=2, label=f'{name} stand spot'))
    ax.set_xlim(-140, 140); ax.set_ylim(-140, 100); ax.set_aspect('equal')
    ax.set_xlabel('B. Locker local x (+ = right side seen from the player)'); ax.set_ylabel('local z (+ = toward the player)')
    ax.legend(loc='lower left', fontsize=8); ax.set_title(f'map {MAP}')
    plt.savefig(os.path.join(HERE, '..', 'results', 'skip', f'skip_{MAP}.png'), dpi=110)
except ImportError:
    pass
