"""Game-accurate sampling of a Kong animation for collision.

Measured from sphere_logger.lua logs (DK 0x40, Lanky 0x17A-0x17C) and the decomp:
  * per game update the animation advances  file speed x global speed (script opcode 0x24,
    animation_state->unk48) x (lag boost / 2); the first update after it starts is a half step
  * each update the active sphere set comes from the CURRENT frame (func_global_asm_80675EE0),
    but the sphere positions come from the PREVIOUS update's pose (bone matrices are built before
    the animation advances)
  * poses interpolate between keyframes like func_global_asm_80619C2C
  * Lanky's arm stretch (animation_state->unk20 bone-scale overrides) comes from logged data
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_g = {'__file__': os.path.join(HERE, 'reach.py'), '__name__': 'reach_helpers'}
_argv = sys.argv; sys.argv = [_argv[0]]
_src = open(os.path.join(HERE, 'reach.py')).read()
exec(_src[:_src.index('sets = D[')], _g)
sys.argv = _argv
D, local, mul, centre, active_set = _g['D'], _g['local'], _g['mul'], _g['centre'], _g['active_set']
SETS = D['sphereSets']

import stretch as _stretch
STRETCH = _stretch.stretch_table()

def step_per_update(an, boost=2):
    return an['speed'] * an.get('gspeed', 1.0) * boost / 2

def updates(an, boost=2):
    """Frames the game evaluates: [(frame_now, frame_of_pose_used_for_spheres), ...]."""
    step = step_per_update(an, boost)
    last = an['frames'] - 1
    frames = [0.0]
    f = step / 2
    while f <= last + 1e-6:
        frames.append(f); f += step
    return list(zip(frames[1:], frames[:-1]))

def _sample(an, pos):
    n = an['frames']; A = min(int(pos), n - 1); B = min(A + 1, n - 1)
    t9 = round((pos - int(pos)) * 1024) if not (an['flags'] & 0x20) else 0
    rot = []
    for ra, rb in zip(an['rot'][A], an['rot'][B]):
        d = ((rb - ra) & 0xFFFF) >> 5
        d = d - 2048 if d & 0x400 else d
        rot.append((ra + (((d * t9) >> 10) << 5)) & 0xFFFF)
    root = [(an['root'][A][i] * 1024 + (an['root'][B][i] - an['root'][A][i]) * t9) / 1024 for i in range(3)]
    return rot, an['scl'][A], root

def pose(kong, an, frame):
    rot, scl, root = _sample(an, frame)
    ov = _stretch.overrides_at(STRETCH, an['anim'], frame)
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

def collision_states(kong, an, boost=2):
    """[(frame_now, pose_frame, active sphere list, bone matrices)] for every game update."""
    sp = kong['collision']['spheres']
    out = []
    for now, prev in updates(an, boost):
        st = active_set(an, int(now))
        if st is None: continue
        act = [sp[k - 1] for k in SETS[st] if k - 1 < len(sp) and sp[k - 1]['r'] > 0]
        out.append((now, prev, act, pose(kong, an, prev)))
    return out
