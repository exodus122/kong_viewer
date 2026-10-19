"""Validate the pose model against a sphere_logger.lua CSV, including the bone-scale overrides
(animation_state->unk20, applied by func_global_asm_8061A61C) and the one-update lag between the
animation pose and the sphere positions.

  python compare_log2.py <log.csv>
"""
import csv, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(HERE, 'reach.py')).read()
argv = sys.argv; sys.argv = [argv[0]]
exec(_src[:_src.index('sets = D[')])

by_anim = {a['anim']: (k, a) for k in D['kongs'] for a in k['anims']}

def sample(an, pos):
    n = an['frames']; A = min(int(pos), n - 1); B = min(A + 1, n - 1)
    t9 = round((pos - int(pos)) * 1024) if not (an['flags'] & 0x20) else 0
    rot = []
    for ra, rb in zip(an['rot'][A], an['rot'][B]):
        d = ((rb - ra) & 0xFFFF) >> 5
        d = d - 2048 if d & 0x400 else d
        rot.append((ra + (((d * t9) >> 10) << 5)) & 0xFFFF)
    root = [(an['root'][A][i] * 1024 + (an['root'][B][i] - an['root'][A][i]) * t9) / 1024 for i in range(3)]
    return rot, an['scl'][A], root

def pose_scaled(kong, an, pos, overrides):
    """Bone matrices with scale overrides: bone a's local rows *= s, bone b's rows /= s (8061A61C)."""
    rot, scl, root = sample(an, pos)
    W = {}
    for i, b in enumerate(kong['bones']):
        c = b['chan']
        L = local(rot[3 * c], rot[3 * c + 1], rot[3 * c + 2], scl[3 * c:3 * c + 3], b['off'])
        for (ba, bb, s) in overrides:
            if b['mtx'] == ba:
                for k in range(3): L[k] = [v * s[k] for v in L[k][:3]] + [0]
            if b['mtx'] == bb:
                for k in range(3): L[k] = [v / s[k] for v in L[k][:3]] + [0]
        P = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [root[0] / 32, root[1] / 32, root[2] / 32, 1]] if i == 0 else W[b['parent']]
        W[b['mtx']] = mul(L, P)
    return W

def parse_scl(extra):
    out = []
    for part in extra.split('|'):
        if part.startswith('scl20=') and len(part) > 6:
            for e in part[6:].split(' '):
                ab, v = e.split(':'); a, b = ab.split('>')
                out.append((int(a), int(b), [float(x) for x in v.split('/')]))
    return out

def rot_y(x, z, deg):
    t = math.radians(deg)
    return x * math.cos(t) + z * math.sin(t), -x * math.sin(t) + z * math.cos(t)

rows = [r for r in csv.DictReader(open(argv[1])) if r['lagged'] != '1']
errs = {}
worst = []
for prev, r in zip(rows, rows[1:]):
    a = int(prev['anim_file'], 16)
    if a not in by_anim or float(prev['scale']) < 0.1 or prev['map'] != r['map'] or prev['control_state'] == '0x87': continue
    if max(abs(float(prev[c])) for c in 'xyz') > 20000: continue
    kong, an = by_anim[a]
    W = pose_scaled(kong, an, float(prev['anim_frame']), parse_scl(prev.get('extra', '')))
    sc = float(prev['scale']); face = int(prev['facing_hex'], 16) * 360 / 4096
    px, py, pz = float(prev['x']), float(prev['y']), float(prev['z'])
    for k in range(1, 17):
        if r.get(f's{k}_active') != '1' or not r[f's{k}_r'] or float(r[f's{k}_r']) <= 0: continue
        s = kong['collision']['spheres'][k - 1]
        c = centre(W, s)
        ox, oz = rot_y(c[0] * sc, c[2] * sc, face)
        m = (px + ox, py + c[1] * sc, pz + oz)
        g = (float(r[f's{k}_x']), float(r[f's{k}_y']), float(r[f's{k}_z']))
        if max(abs(v) for v in g) > 20000: continue
        e = math.dist(m, g)
        errs.setdefault(k, []).append(e)
        worst.append((e, r['emu_frame'], prev['anim_file'], prev['anim_frame'], k))
print('mean error per sphere (world units):', {k: round(sum(v) / len(v), 3) for k, v in sorted(errs.items())})
print('max error per sphere:', {k: round(max(v), 3) for k, v in sorted(errs.items())})
worst.sort(reverse=True)
print('worst rows:', [(round(e, 2), f, a, p, k) for e, f, a, p, k in worst[:6]])
