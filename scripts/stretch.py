"""Bone-scale overrides (animation_state->unk20, func_global_asm_8061A61C) measured from
sphere_logger.lua logs. Lanky's attacks stretch an arm this way at runtime; the values are not in
the animation files. The writer isn't decompiled, so the curves come from logs.

stretch_table() -> {anim_file: [(bone_a, bone_b, [(anim_frame, (sx, sy, sz)), ...]), ...]}
overrides_at(table, anim_file, frame) -> [(bone_a, bone_b, (sx, sy, sz))]  (linear in frame, max of samples)
"""
import csv, glob, os

HERE = os.path.dirname(os.path.abspath(__file__))

def stretch_table(pattern=os.path.join(HERE, '..', 'results', 'logs', 'kong_spheres_*.csv')):
    samples = {}
    for path in glob.glob(pattern):
        for r in csv.DictReader(open(path)):
            if r.get('lagged') == '1' or not r.get('extra'): continue
            try: anim = int(r['anim_file'], 16); fr = float(r['anim_frame'])
            except ValueError: continue
            for part in r['extra'].split('|'):
                if not part.startswith('scl20=') or len(part) <= 6: continue
                for e in part[6:].split(' '):
                    ab, v = e.split(':'); a, b = (int(x) for x in ab.split('>'))
                    s = tuple(float(x) for x in v.split('/'))
                    samples.setdefault((anim, a, b), {})
                    key = round(fr, 2)
                    old = samples[(anim, a, b)].get(key)
                    if old is None or max(s) > max(old): samples[(anim, a, b)][key] = s
    table = {}
    for (anim, a, b), pts in samples.items():
        if all(max(abs(c - 1) for c in s) < 1e-3 for s in pts.values()): continue
        table.setdefault(anim, []).append((a, b, sorted(pts.items())))
    return table

def overrides_at(table, anim, frame):
    out = []
    for a, b, pts in table.get(anim, []):
        if frame <= pts[0][0]: s = pts[0][1]
        elif frame >= pts[-1][0]: s = pts[-1][1]
        else:
            for (f0, s0), (f1, s1) in zip(pts, pts[1:]):
                if f0 <= frame <= f1:
                    t = (frame - f0) / (f1 - f0) if f1 > f0 else 0
                    s = tuple(x + (y - x) * t for x, y in zip(s0, s1)); break
        out.append((a, b, s))
    return out

if __name__ == '__main__':
    for anim, lst in sorted(stretch_table().items()):
        for a, b, pts in lst:
            print(hex(anim), f'{a}>{b}', ' '.join(f'f{f}:{s[1]:.2f}' for f, s in pts))
