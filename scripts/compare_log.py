"""Compare logged in-game sphere positions (sphere_logger.lua CSV) with the viewer's pose maths.

  python compare_log.py <log.csv> [kong name, default from the anim file]
For every non-lag row it re-poses the logged animation file at the logged frame from the logged
position / facing / scale, and prints game-vs-model error for each active sphere.
"""
import csv, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(HERE, 'reach.py')).read()
argv = sys.argv; sys.argv = [argv[0]]
exec(_src[:_src.index('sets = D[')])
log = argv[1]

by_anim = {}
for k in D['kongs']:
    for a in k['anims']:
        by_anim[a['anim']] = (k, a)

def sample(an, pos):
    """Interpolated channel values like func_global_asm_80619C2C (frame A + fraction toward A+1)."""
    n = an['frames']; A = min(int(pos), n - 1); B = min(A + 1, n - 1)
    t9 = round((pos - int(pos)) * 1024) if not (an['flags'] & 0x20) else 0
    rot = []
    for ra, rb in zip(an['rot'][A], an['rot'][B]):
        d = ((rb - ra) & 0xFFFF) >> 5
        d = d - 2048 if d & 0x400 else d
        rot.append((ra + (((d * t9) >> 10) << 5)) & 0xFFFF)
    root = [(an['root'][A][i] * 1024 + (an['root'][B][i] - an['root'][A][i]) * t9) / 1024 for i in range(3)]
    return rot, an['scl'][A], root

def pose_at(kong, an, pos):
    rot, scl, root = sample(an, pos)
    tmp = dict(an); tmp['rot'] = [rot]; tmp['scl'] = [scl]; tmp['root'] = [root]
    return pose(kong, tmp, 0)

def rot_y(x, z, deg):
    t = math.radians(deg)
    return x * math.cos(t) + z * math.sin(t), -x * math.sin(t) + z * math.cos(t)

errs = {}
for r in csv.DictReader(open(log)):
    if r['lagged'] == '1': continue
    a = int(r['anim_file'], 16)
    if a not in by_anim: continue
    kong, an = by_anim[a]
    fr = float(r['anim_frame']); sc = float(r['scale'])
    if sc < 0.1: continue
    px, py, pz = float(r['x']), float(r['y']), float(r['z'])
    face = int(r['facing_hex'], 16) * 360 / 4096
    W = pose_at(kong, an, fr)
    line = []
    for k in range(1, 17):
        if r.get(f's{k}_active') != '1' or not r[f's{k}_r'] or float(r[f's{k}_r']) <= 0: continue
        s = kong['collision']['spheres'][k - 1]
        c = centre(W, s)
        ox, oz = rot_y(c[0] * sc, c[2] * sc, face)
        m = (px + ox, py + c[1] * sc, pz + oz)
        g = (float(r[f's{k}_x']), float(r[f's{k}_y']), float(r[f's{k}_z']))
        e = math.dist(m, g)
        errs.setdefault(k, []).append(e)
        if k in (6, 7):
            line.append(f'#{k} game ({g[0]:.1f},{g[1]:.1f},{g[2]:.1f}) model ({m[0]:.1f},{m[1]:.1f},{m[2]:.1f}) err {e:.1f}')
    if line:
        print(f"{r['emu_frame']} anim {r['anim_file']} f{fr:5.2f}  " + ' | '.join(line))
print('\nmean error per sphere:', {k: round(sum(v) / len(v), 2) for k, v in sorted(errs.items())})
