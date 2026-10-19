"""Extract Kong skeletons, collision spheres, meshes and animations from a DK64 (US) ROM.

Formats reverse engineered from the dk64 decomp:
  actor model header   ActorModelHeader (include/structs.h), relocated in func_global_asm_80612E90
  collision table      func_global_asm_8066E2C0 (sphere list -> LedgeInfo8C)
  sphere transform     func_global_asm_80671880
  animation decode     func_global_asm_80619C2C (src/global_asm/code_1E2D0.s)
  bone matrices        func_global_asm_806195D0 / 8061A938 (same file)
  animation scripts    D_global_asm_80746BEC handlers (src/global_asm/code_18750.c)
"""
import base64, gzip, json, struct, sys, os, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ptr

# Animation names from ScriptHawk (github.com/Isotarge/ScriptHawk, games/dk64.lua), keyed by anim-code script index
NAMES = {}
for line in open(os.path.join(HERE, 'names_raw.txt')):
    if '=' in line:
        k, v = line.rstrip('\n').split('=', 1)
        NAMES[int(k, 16)] = v
ACTIONS = json.load(open(os.path.join(HERE, 'action_types.json')))
# Player control-state names from ScriptHawk, keyed by Actor.control_state
CONTROL_STATES = {}
for line in open(os.path.join(HERE, 'control_states.txt')):
    if '=' in line:
        k, v = line.rstrip('\n').split('=', 1)
        CONTROL_STATES[int(k, 16)] = v

KONGS = [  # (name, model index, anim-type table column)
    ("DK", 4, 0), ("Diddy", 1, 1), ("Lanky", 6, 2), ("Tiny", 9, 3), ("Chunky", 12, 4),
]

def be16(b, o): return struct.unpack_from('>h', b, o)[0]
def bu16(b, o): return struct.unpack_from('>H', b, o)[0]
def bu32(b, o): return struct.unpack_from('>I', b, o)[0]
def bf32(b, o): return struct.unpack_from('>f', b, o)[0]

# ---------------------------------------------------------------- models
def parse_model(model_index, hand_segs=(7,)):
    f = ptr.get_file(5, model_index - 1)
    base = bu32(f, 0)
    rel = lambda p: p - base + 0x28
    p_dls, p_bones, p_coll, p_end = bu32(f, 4), bu32(f, 8), bu32(f, 0xC), bu32(f, 0x10)
    bone_count, dl_count = f[0x20], f[0x21]

    bones = []
    for i in range(bone_count):
        o = rel(p_bones) + 16 * i
        bones.append(dict(parent=f[o], mtx=f[o + 1], chan=f[o + 2],
                          off=[bf32(f, o + 4), bf32(f, o + 8), bf32(f, o + 12)]))

    # collision table (func_global_asm_8066E2C0)
    o = rel(p_coll)
    coll = dict(broad=bf32(f, o), broad2=bf32(f, o + 4))
    o += 8
    n = bu32(f, o); o += 4
    spheres = []
    for i in range(n):
        x, y, z, r = struct.unpack_from('>4f', f, o)
        field = struct.unpack_from('>i', f, o + 16)[0]
        spheres.append(dict(pos=[x, y, z], r=r, mtx=(-1 if field == -1 else field >> 6)))
        o += 0x14
    n = bu32(f, o); o += 4
    points = []
    for i in range(n):
        x, y, z = struct.unpack_from('>3f', f, o)
        field = struct.unpack_from('>i', f, o + 12)[0]
        points.append(dict(pos=[x, y, z], field=field))
        o += 0x10
    coll.update(spheres=spheres, points=points)

    # mesh: walk the display lists (F3DEX2) like 3d_model_viewer's walkDK64DisplayList: the bone matrix comes from
    # each G_MTX, and each triangle's texture is worked out when it is drawn, from the tile G_TEXTURE selects,
    # the TMEM address that tile reads, and the image last loaded there
    verts, tris, tri_mat = [], [], []
    vbuf = [None] * 64
    cur_mtx = 0
    dl_ptrs = [bu32(f, rel(p_dls) + 4 * i) for i in range(dl_count)]
    seg_base = {3: 0x28}
    # animated textures (eyes, mouths): header +0x10 -> u16 count, then per entry u16 frames, u16 segment,
    # u16, u16 table-25 ids[frames]; a G_SETTIMG into that segment shows the first frame
    seg_tex = {}
    if bu32(f, 0x10):
        q = rel(bu32(f, 0x10)); cnt = bu16(f, q); q += 2
        for _ in range(cnt):
            frames, seg = bu16(f, q), bu16(f, q + 2)
            if frames: seg_tex[seg] = bu16(f, q + 6)
            q += 6 + 2 * frames
    tiles = [dict(fmt=0, siz=0, line=0, tmem=0, cms=0, cmt=0, shifts=0, shiftt=0, uls=0, ult=0, lrs=0, lrt=0) for _ in range(8)]
    tmem = {}                                    # TMEM address -> (table-25 id, odd rows pre-swapped)
    st = dict(timg=-1, tex_on=False, tex_tile=0, sc=(1.0, 1.0), geom=0, uses_tex=True, uses_alpha=True)
    shift_scale = lambda sh: 1.0 if sh == 0 else (1.0 / (1 << sh) if sh <= 10 else float(1 << (16 - sh)))
    materials, mat_index = [], {}

    def current_material():
        tile = tiles[st['tex_tile']]
        tex = None
        if st['tex_on'] and st['uses_tex']:
            tid, swapped = tmem.get(tile['tmem'], (-1, False))
            w, h = ((tile['lrs'] - tile['uls']) >> 2) + 1, ((tile['lrt'] - tile['ult']) >> 2) + 1
            if tid >= 0 and 0 < w <= 1024 and 0 < h <= 1024:
                tex = (tid, w, h, tile['line'], tile['fmt'], tile['siz'], tile['cms'], tile['cmt'], st['uses_alpha'], swapped)
        key = (tex, st['geom'] & 0x600)
        if key not in mat_index:
            mat_index[key] = len(materials)
            if tex:
                tid, w, h, line, fmt, siz, cms, cmt, alpha, swapped = tex
                materials.append(dict(tex=tid, w=w, h=h, line=line, fmt=fmt, siz=siz, wrapS=cms, wrapT=cmt,
                                      alpha=alpha, swapped=swapped, cull=key[1]))
            else:
                materials.append(dict(tex=None, cull=key[1]))       # cull: 0x400 back, 0x200 front
        return mat_index[key], tex

    def emit(a, b, c):
        if vbuf[a] is None or vbuf[b] is None or vbuf[c] is None: return
        mi, tex = current_material()
        tile = tiles[st['tex_tile']]
        ss = shift_scale(tile['shifts']) * st['sc'][0] / 32
        stt = shift_scale(tile['shiftt']) * st['sc'][1] / 32
        idx = []
        for k in (a, b, c):
            v = vbuf[k]
            uv = [0.0, 0.0]
            if tex:
                uv = [round((v['s'] * ss - tile['uls'] / 4) / tex[1], 5), round((v['t'] * stt - tile['ult'] / 4) / tex[2], 5)]
            verts.append(dict(p=v['p'], n=v['n'], m=v['m'], uv=uv, col=v['col']))
            idx.append(len(verts) - 1)
        tris.append(idx); tri_mat.append(mi)

    def run_dl(off, depth=0):
        nonlocal cur_mtx
        while off + 8 <= len(f):
            w0, w1 = bu32(f, off), bu32(f, off + 4)
            op = w0 >> 24
            off += 8
            if op == 0xDA:  # G_MTX
                if (w1 >> 24) == 4:
                    cur_mtx = (w1 & 0xFFFFFF) // 0x40
            elif op == 0x01:  # G_VTX
                nv = (w0 >> 12) & 0xFF
                v0 = ((w0 >> 1) & 0x7F) - nv
                seg, a = w1 >> 24, w1 & 0xFFFFFF
                if seg not in seg_base: continue
                vo = seg_base[seg] + a
                for k in range(nv):
                    q = vo + 16 * k
                    if not 0 <= v0 + k < 64: continue
                    x, y, z = struct.unpack_from('>3h', f, q)
                    s_, t_ = struct.unpack_from('>2h', f, q + 8)
                    nx, ny, nz = struct.unpack_from('>3b', f, q + 12)
                    vbuf[v0 + k] = dict(p=[x, y, z], n=[nx, ny, nz], m=cur_mtx, s=s_, t=t_, col=list(f[q + 12:q + 15]))
            elif op == 0x05:  # G_TRI1
                emit(*[((w0 >> sh) & 0xFF) // 2 for sh in (16, 8, 0)])
            elif op in (0x06, 0x07):  # G_TRI2 / G_QUAD
                emit(*[((w0 >> sh) & 0xFF) // 2 for sh in (16, 8, 0)])
                emit(*[((w1 >> sh) & 0xFF) // 2 for sh in (16, 8, 0)])
            elif op == 0xD7:  # G_TEXTURE
                st['tex_on'] = ((w0 >> 1) & 0x7F) != 0
                st['tex_tile'] = (w0 >> 8) & 7
                st['sc'] = ((w1 >> 16) / 65536.0, (w1 & 0xFFFF) / 65536.0)
            elif op == 0xD9:  # G_GEOMETRYMODE: clear then set
                st['geom'] = (st['geom'] & (w0 & 0xFFFFFF)) | w1
            elif op == 0xFC:  # G_SETCOMBINE: cycle-1 colour and both cycles' alpha inputs, 1/2 = TEXEL0/1
                a_, c_ = (w0 >> 20) & 0xF, (w0 >> 15) & 0x1F
                b_, d_ = (w1 >> 28) & 0xF, (w1 >> 15) & 7
                alpha_in = [(w0 >> 12) & 7, (w1 >> 12) & 7, (w0 >> 9) & 7, (w1 >> 9) & 7,
                            (w1 >> 21) & 7, (w1 >> 3) & 7, (w1 >> 18) & 7, w1 & 7]
                st['uses_alpha'] = any(x in (1, 2) for x in alpha_in)
                st['uses_tex'] = any(x in (1, 2) for x in (a_, b_, c_, d_)) or st['uses_alpha']
            elif op == 0xFD:  # G_SETTIMG: segment 0 = a table-25 id, otherwise an animated texture's segment
                st['timg'] = w1 if (w1 >> 24) == 0 else seg_tex.get(w1 >> 24, -1)
            elif op == 0xF5:  # G_SETTILE
                t = tiles[(w1 >> 24) & 7]
                t.update(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3, line=(w0 >> 9) & 0x1FF, tmem=w0 & 0x1FF,
                         cmt=(w1 >> 18) & 3, shiftt=(w1 >> 10) & 0xF, cms=(w1 >> 8) & 3, shifts=w1 & 0xF)
            elif op == 0xF2:  # G_SETTILESIZE
                t = tiles[(w1 >> 24) & 7]
                t.update(uls=(w0 >> 12) & 0xFFF, ult=w0 & 0xFFF, lrs=(w1 >> 12) & 0xFFF, lrt=w1 & 0xFFF)
            elif op in (0xF3, 0xF4, 0xF0):  # G_LOADBLOCK / G_LOADTILE / G_LOADTLUT
                # A G_LOADBLOCK with dxt 0 doesn't swap odd rows as it loads, but sampling still un-swaps
                # them, so such textures are stored in the ROM with odd rows' 32-bit words pre-swapped
                swapped = op == 0xF3 and (w1 & 0xFFF) == 0
                tmem[tiles[(w1 >> 24) & 7]['tmem']] = (st['timg'], swapped)
            elif op == 0xDE:  # G_DL
                seg, a = w1 >> 24, w1 & 0xFFFFFF
                branch = (w0 >> 16) & 0xFF == 1
                if seg >= 7 and branch:
                    # hand-state switch (func_global_asm_8061324C / 80614C38). Bit set: the segment
                    # points right after this branch, so block A is drawn, then block B.
                    # Bit clear: it points at the marker {0x00000000, seg}, so only block B is drawn.
                    # For DK/Lanky/Tiny/Chunky segment 7's block A is the hand and segment 8's is the gun;
                    # for Diddy both are his peanut guns.
                    if seg in hand_segs:
                        continue
                    q = off
                    while q + 8 <= len(f) and not (bu32(f, q) == 0 and bu32(f, q + 4) == seg):
                        q += 8
                    off = q
                    continue
                if seg == 3 and depth < 8:
                    run_dl(seg_base[3] + a, depth + 1)
                if branch:
                    return
            elif op == 0xDF:  # G_ENDDL
                return

    for p in dl_ptrs:
        run_dl(rel(p))

    # dedupe vertices (same position/normal/bone/uv)
    key_to_i, vout, remap = {}, [], []
    for v in verts:
        k = (tuple(v['p']), tuple(v['n']), v['m'], tuple(v['uv']))
        if k not in key_to_i:
            key_to_i[k] = len(vout); vout.append(v)
        remap.append(key_to_i[k])
    tris = [[remap[i] for i in t] for t in tris]

    return dict(model=model_index, bones=bones, collision=coll,
                mesh=dict(pos=[c for v in vout for c in v['p']],
                          nrm=[c for v in vout for c in v['n']],
                          bone=[v['m'] for v in vout],
                          uv=[c for v in vout for c in v['uv']],
                          col=[c for v in vout for c in v['col']],
                          tri=[i for t in tris for i in t],
                          mat=tri_mat, materials=materials))

def decode_texture(index, w, h, line=0, swapped=False):
    """RGBA16 (5551) texture from pointer table 25 -> RGBA8 bytes; `line` is the tile's row stride in
    64-bit words (as 3d_model_viewer's decodeDK64Texture). `swapped`: odd rows have the two 32-bit words
    of every 64-bit TMEM word exchanged (loaded by G_LOADBLOCK with dxt 0). Missing texels are magenta."""
    t = ptr.get_file(25, index)
    stride = line * 8 if line else w * 2
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            o, p = y * stride + 2 * x, 4 * (y * w + x)
            if swapped and y & 1: o ^= 4
            if o + 2 > len(t):
                out[p:p + 4] = bytes((255, 0, 255, 255)); continue
            c = (t[o] << 8) | t[o + 1]
            r, g, b_ = (c >> 11) & 31, (c >> 6) & 31, (c >> 1) & 31
            out[p:p + 4] = bytes(((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b_ << 3) | (b_ >> 2), 255 if c & 1 else 0))
    return bytes(out)

# ---------------------------------------------------------------- animations
class Bits:
    def __init__(self, data, off):
        self.d, self.bit = data, off * 8
    def read(self, n):
        v = 0
        for _ in range(n):
            byte = self.d[self.bit >> 3] if (self.bit >> 3) < len(self.d) else 0
            v = (v << 1) | ((byte >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return v

def parse_anim(index):
    f = ptr.get_file(11, index)
    if len(f) < 0x14: return None
    flags = be16(f, 4)
    data_off = be16(f, 6) + 6          # loader adds 6 (func_global_asm_80613?? in code_18750.c)
    root_base = [be16(f, 8), be16(f, 0xA), be16(f, 0xC)]
    root_bits = [f[0xE], f[0xF], f[0x10]]
    nchan = f[0x11] - 1
    frames = f[0x12]
    stride = f[0x13]
    # component descriptors
    comps, o = [], 0x14
    for _ in range(3 * nchan):
        d = bu16(f, o)
        if d & 0x10:
            d2 = bu16(f, o + 2)
            comps.append((d, d2)); o += 4
        else:
            comps.append((d, None)); o += 2
    out_frames = []
    for fr in range(frames):
        b = Bits(f, data_off + fr * stride)
        root = [root_base[i] + (b.read(root_bits[i]) if root_bits[i] else 0) for i in range(3)]
        rot, scl = [], []
        for d, d2 in comps:
            nb = d & 0xF
            a = b.read(nb) if nb else 0
            rot.append(((d & 0xFFF0) + (a << 5)) & 0xFFFF)
            if d2 is None:
                scl.append(0)
            else:
                nb2 = 16 if d2 == 0 else (d2 & 0xF)
                if d2 != 0 and nb2 == 0:
                    scl.append(d2)
                else:
                    s0 = 0 if d2 == 0 else (d2 ^ nb2)
                    a2 = b.read(nb2)
                    scl.append((s0 + (a2 << 4)) & 0xFFFF)
        out_frames.append(dict(root=root, rot=rot, scl=scl))
    return dict(index=index, flags=flags, speed=bf32(f, 0), nchan=nchan, frames=frames,
                sclmask=[0 if d2 is None else 1 for d, d2 in comps],
                data=out_frames)

# ---------------------------------------------------------------- scripts
OPS = json.load(open(os.path.join(HERE, 'opcodes.json')))
OPLEN = {o['op']: o['length'] for o in OPS}
SET_ANIM_RAW = {0x14, 0x15, 0x17, 0x4F}          # file index (func_global_asm_80613C48/80613CA8/80614014)
SET_ANIM_GENERIC = {0x18, 0x19, 0x1A, 0x50}      # generic id, remapped per actor via D_global_asm_807FBB58
STOP = {0x27, 0x29, 0x34, 0x35, 0x47, 0x54}

def script_anims(code, sidx):
    """Return (anim file indices, chained script indices, chained anim types) reachable from a script."""
    start = bu32(code, 4 * sidx)
    anims, chains, types = [], set(), set()
    todo, seen = [0], set()
    while todo:
        pc = todo.pop()
        steps = 0
        while pc not in seen and steps < 400:
            seen.add(pc); steps += 1
            if start + pc >= len(code): break
            op = code[start + pc]
            if op >= len(OPS): break
            if op in SET_ANIM_RAW or op in SET_ANIM_GENERIC:
                a = (('g' if op in SET_ANIM_GENERIC else 'r'), bu16(code, start + pc + 1) & 0x3FFF)
                if a not in anims: anims.append(a)
            if op in (0x4D, 0x4E):
                q = pc + 1
                while True:
                    t = code[start + q]
                    if t == 0: q += 1; break
                    if 1 <= t <= 6:
                        todo.append(be16(code, start + q + 3)); q += 5
                    elif t == 7:
                        q += 5
                    else:
                        break
                pc = q; continue
            if op == 0x2F:
                pc = be16(code, start + pc + 1); continue
            if op in (0x30, 0x31, 0x32, 0x33):
                todo.append(be16(code, start + pc + 1))
            if op == 0x25:
                chains.add(bu16(code, start + pc + 1)); break
            if op in (0x26, 0x58):
                types.add(bu16(code, start + pc + 1)); break
            if op == 0x28 or op in STOP:
                break
            n = OPLEN.get(op, 0)
            if n == 0: break
            pc += n
    return anims, chains, types

def sphere_tables():
    """Per-animation active sphere sets (func_global_asm_80675EE0 / 8067605C), read from the
    gzip-compressed global_asm .data in the ROM (vram 0x80744460, ROM 0xC29D4)."""
    data = zlib.decompressobj(31).decompress(ptr._d()[0xC29D4:0xC29D4 + 0x20000])
    at = lambda vram: vram - 0x80744460
    sets = []
    for i in range((0x80748F58 - 0x80748E50) // 9):        # D_global_asm_80748E50: 9-byte lists, 0xFF-terminated
        lst = []
        for x in data[at(0x80748E50) + 9 * i: at(0x80748E50) + 9 * i + 9]:
            if x == 0xFF: break
            lst.append(x)                                     # 1-based sphere numbers
        sets.append(lst)
    windows, o = {}, at(0x80748FE8)                           # D_global_asm_80748FE8: 12-byte entries, anim -1 ends
    while True:
        a, f0, f1, dmg, u8, st, fl, _ = struct.unpack_from('>hhhhBbBb', data, o)
        if a == -1: break
        windows.setdefault(a, []).append([f0, f1, st])
        o += 12
    masks = {}                                                # D_global_asm_80748F58: {s16 actor, u8 sphere, pad, u16 mask} x 0x18
    for i in range(0x18):
        actor, sph, m = struct.unpack_from('>hBxH', data, at(0x80748F58) + 6 * i)
        masks.setdefault(actor, {})[sph] = m
    return sets, windows, masks

def script_speeds(code, sidx, n_generic, tab58, col):
    """Global animation speed (animation_state->unk48, opcode 0x24 / func_global_asm_80614D00) that
    applies to each animation a script starts, following the script's main path."""
    start = bu32(code, 4 * sidx)
    out, pending, speed, pc = {}, [], None, 0
    for _ in range(200):
        if start + pc >= len(code): break
        op = code[start + pc]
        if op in SET_ANIM_RAW or op in SET_ANIM_GENERIC:
            v = bu16(code, start + pc + 1) & 0x3FFF
            a = tab58[v][col] if op in SET_ANIM_GENERIC and v < n_generic else v
            pending.append(a)
        if op == 0x24:
            speed = struct.unpack_from('>f', code, start + pc + 1)[0]
            for a in pending: out.setdefault(a, speed)
            pending = []
        if op in STOP or op in (0x25, 0x26, 0x28, 0x2F, 0x4D, 0x4E): break
        n = OPLEN.get(op, 0)
        if n == 0: break
        pc += n
    for a in pending: out.setdefault(a, speed if speed is not None else 1.0)
    return out

def main(out_path):
    code = ptr.get_file(13, 0)
    n_scripts = bu32(code, 0) // 4
    t54 = bu32(code, 12)
    # anim-type table: 7 columns of u16 script indices, ends where script data begins
    first_script_data = min(bu32(code, 4 * i) for i in range(4, n_scripts) if bu32(code, 4 * i) > t54)
    n_types = (first_script_data - t54) // 14
    typetab = [[bu16(code, t54 + 2 * (r * 7 + c)) for c in range(7)] for r in range(n_types)]
    t58 = bu32(code, 8)
    n_generic = (t54 - t58) // 14
    tab58 = [[bu16(code, t58 + 2 * (r * 7 + c)) for c in range(7)] for r in range(n_generic)]
    n_anims = len(ptr.table_entries(11)) - 1
    print('scripts', n_scripts, 'anim types', n_types, 'generic ids', n_generic, 'anim files', n_anims)

    anim_cache = {}
    def anim(i):
        if i not in anim_cache:
            try: anim_cache[i] = parse_anim(i)
            except Exception as e: anim_cache[i] = None
        return anim_cache[i]

    SETS, WINDOWS, MASKS = sphere_tables()
    result = dict(kongs=[], sphereSets=SETS)
    passes = []
    for name, model_index, col in KONGS:
        m = parse_model(model_index, hand_segs=(() if name == 'Diddy' else (7,)))   # hands on, guns off
        nchan = max(b['chan'] for b in m['bones']) + 1
        # every generic animation id for this Kong (D_global_asm_807FBB58 column)
        entries = {}
        type_anims = {}
        gspeed = {}
        def add(a, script=None, typ=None, gen=None):
            A = anim(a)
            if not A or A['nchan'] != nchan or A['frames'] <= 0: return
            e = entries.setdefault(a, dict(anim=a, scripts=set(), types=set(), generic=set()))
            if script is not None: e['scripts'].add(script)
            if typ is not None: e['types'].add(typ)
            if gen is not None: e['generic'].add(gen)
        for g in range(n_generic):
            add(tab58[g][col], gen=g)
        # scripts reachable from this Kong's anim types (for labels)
        for t in range(n_types):
            stack, visited = [(typetab[t][col], t)], set()
            while stack:
                sidx, typ = stack.pop()
                if sidx in visited or sidx < 4 or sidx >= n_scripts: continue
                visited.add(sidx)
                anims, chains, types = script_anims(code, sidx)
                for a, sv in script_speeds(code, sidx, n_generic, tab58, col).items(): gspeed.setdefault(a, sv)
                for kind, v in anims:
                    a = tab58[v][col] if kind == 'g' and v < n_generic else (v if kind == 'r' and v < n_anims else None)
                    if a is None: continue
                    add(a, script=sidx, typ=typ, gen=(v if kind == 'g' else None))
                    if a in entries and typ == t:
                        type_anims.setdefault(t, [])
                        if a not in type_anims[t]: type_anims[t].append(a)
                for c in chains: stack.append((c, typ))
                for ty in types:
                    if ty < n_types: stack.append((typetab[ty][col], ty))
        # scripts the player code starts directly (playActorAnimation(actor, script)), e.g. Chunky's
        # Primate Punch. Only keep files inside this Kong's own range of animation files.
        lo, hi = min(entries), max(a for a in entries if a < 0x1000)
        direct_anims = {}
        for sidx in ACTIONS.get('direct_scripts', []):
            if sidx < 4 or sidx >= n_scripts: continue
            stack, visited = [sidx], set()
            while stack:
                s2 = stack.pop()
                if s2 in visited or s2 < 4 or s2 >= n_scripts: continue
                visited.add(s2)
                anims, chains, _ = script_anims(code, s2)
                for a, sv in script_speeds(code, s2, n_generic, tab58, col).items(): gspeed.setdefault(a, sv)
                for kind, v in anims:
                    a = tab58[v][col] if kind == 'g' and v < n_generic else (v if kind == 'r' and v < n_anims else None)
                    if a is None or not (lo <= a <= hi): continue
                    add(a, script=sidx)
                    if a in entries: direct_anims.setdefault(sidx, []).append(a)
                stack.extend(chains)
        passes.append((name, col, m, nchan, entries, type_anims, direct_anims, gspeed))

    # Labels, from the game code: the player code sets a control state and then calls
    # playAnimation(actor, type) (action_types.json, built by action_types.py). The type's
    # script for this Kong plays the animation file(s). Control-state names are from ScriptHawk.
    # ScriptHawk's per-animation list (names_raw.txt) only matches DK's file indices below 0x3E,
    # so it is used only there, as a fallback, and carried to the other Kongs via the generic-id table.
    import re as _re
    action_types = {int(k): v for k, v in ACTIONS.items() if k.isdigit()}
    dk_names = {k: v for k, v in NAMES.items() if '(DK' in v and k < 0x3E}
    for name, col, m, nchan, entries, type_anims, direct_anims, gspeed in passes:
        rename = lambda s: _re.sub(r'\bDK\b', name, s)
        labels = {}
        def label(a, text):
            if a in entries and text and text not in labels.setdefault(a, []): labels[a].append(text)
        for t in sorted(type_anims):
            states = [s for s in action_types.get(t, []) if s in CONTROL_STATES]
            if not states: continue
            lst = type_anims[t]
            for i, a in enumerate(lst):
                part = f' (part {i + 1}/{len(lst)})' if len(lst) > 1 else ''
                label(a, ' / '.join(dict.fromkeys(CONTROL_STATES[x] for x in states)) + f'{part} · type 0x{t:X}')
        for sidx, lst in sorted(direct_anims.items()):
            states = [x for x in ACTIONS.get('s%d' % sidx, []) if x in CONTROL_STATES]
            if not states: continue
            lst = list(dict.fromkeys(lst))
            for i, a in enumerate(lst):
                part = f' (part {i + 1}/{len(lst)})' if len(lst) > 1 else ''
                label(a, ' / '.join(dict.fromkeys(CONTROL_STATES[x] for x in states)) + f'{part} · script 0x{sidx:X}')
        for g in range(n_generic):
            dka = tab58[g][0]
            if dka in dk_names: label(tab58[g][col], rename(dk_names[dka]))
        anims_out = []
        for a in sorted(entries):
            A = anim(a)
            anims_out.append(dict(anim=a, names=labels.get(a, []),
                                  scripts=sorted(entries[a]['scripts']), types=sorted(entries[a]['types']),
                                  generic=sorted(entries[a]['generic']),
                                  frames=A['frames'], flags=A['flags'], speed=A['speed'],
                                  gspeed=gspeed.get(a, 1.0),
                                  sclmask=A['sclmask'], windows=WINDOWS.get(a, []),
                                  root=[fr['root'] for fr in A['data']],
                                  rot=[fr['rot'] for fr in A['data']],
                                  scl=[fr['scl'] for fr in A['data']]))
        m.update(name=name, nchan=nchan, anims=anims_out, masks=MASKS.get(col + 2, {}))
        result['kongs'].append(m)
        print(name, 'bones', len(m['bones']), 'verts', len(m['mesh']['bone']), 'tris', len(m['mesh']['tri']) // 3,
              'spheres', len(m['collision']['spheres']), 'anims', len(anims_out),
              'named', sum(1 for x in anims_out if x['names']))
    try:
        import stretch
        result['stretch'] = {str(a): [[ba, bb, [[f, list(v)] for f, v in pts]] for ba, bb, pts in lst]
                             for a, lst in stretch.stretch_table().items()}
    except Exception as e:
        print('no stretch data:', e)
    # textures used by the Kongs' materials, shared between Kongs: {index: {w, h, rgba (base64 RGBA8)}}
    textures = {}
    for k in result['kongs']:
        for mat in k['mesh']['materials']:
            if mat['tex'] is None: continue
            key = f"{mat['tex']}_{mat['w']}x{mat['h']}_{mat['line']}_{int(mat['alpha'])}_{int(mat['swapped'])}"
            mat['key'] = key
            if key not in textures:
                rgba = bytearray(decode_texture(mat['tex'], mat['w'], mat['h'], mat['line'], mat['swapped']))
                if not mat['alpha']: rgba[3::4] = bytes([255]) * (len(rgba) // 4)     # the combiner ignores its alpha
                textures[key] = dict(w=mat['w'], h=mat['h'], rgba=base64.b64encode(bytes(rgba)).decode())
    result['textures'] = textures
    print(len(textures), 'textures')
    raw = json.dumps(result, separators=(',', ':')).encode()
    if out_path.endswith('.js'):
        # loadable from file:// via <script src>; the viewer gunzips it with DecompressionStream
        b64 = base64.b64encode(gzip.compress(raw, 9)).decode()
        with open(out_path, 'w') as fo:
            fo.write('// Generated by extract.py from your own DK64 ROM. Do not redistribute.\n')
            fo.write('window.KONG_DATA_GZ_B64 = "' + b64 + '";\n')
    else:
        open(out_path, 'wb').write(raw)
    print('wrote', out_path, os.path.getsize(out_path))

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Extract Kong models, collision spheres and animations for the viewer.')
    ap.add_argument('--rom', default=None, help='US DK64 ROM (.z64). Default: the decomp root baserom.us.z64')
    ap.add_argument('out', nargs='?', default=os.path.join(HERE, '..', 'kong_data.js'),
                    help='output .js (for index.html) or .json')
    args = ap.parse_args()
    if args.rom:
        ptr.load_rom(args.rom)
    main(args.out)
