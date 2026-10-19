"""DK64 (US) pointer-table file access.

Mirrors getPointerTableFile / func_global_asm_8066B4D4 (src/global_asm/code_6AF80.c):
  - the pointer tables live at ROM 0x101C50 (gOverlayTable[11].rom_code_start)
  - 32 u32 table offsets, each table is a list of u32 file offsets (relative to the base)
  - bit 31 set = redirect: the s16 at that offset is the real file index
  - tables flagged in D_global_asm_80748E18 are gzip-compressed
"""
import os
import struct
import zlib

BASE = 0x101C50
COMPRESSED = [1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 1, 1, 0,
              1, 1, 1, 1, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0]  # D_global_asm_80748E18

_rom = None


def load_rom(path):
    global _rom
    with open(path, 'rb') as fh:
        _rom = fh.read()
    if _rom[:4] != b'\x80\x37\x12\x40':
        raise SystemExit(f'{path}: expected a big-endian (.z64) ROM')


def _d():
    if _rom is None:
        here = os.path.dirname(os.path.abspath(__file__))
        load_rom(os.environ.get('DK64_ROM', os.path.join(here, '..', '..', '..', 'baserom.us.z64')))
    return _rom


def table_entries(t):
    d = _d()
    o = struct.unpack_from('>I', d, BASE + 4 * t)[0]
    first = struct.unpack_from('>I', d, BASE + o)[0] & 0x7FFFFFFF
    n = (first - o) // 4
    return [struct.unpack_from('>I', d, BASE + o + 4 * i)[0] for i in range(n)]


def get_file(t, i):
    d = _d()
    ents = table_entries(t)
    e = ents[i]
    if e & 0x80000000:
        redirect = struct.unpack_from('>h', d, BASE + (e & 0x7FFFFFFF))[0]
        return get_file(t, redirect)
    nxt = ents[i + 1] & 0x7FFFFFFF if i + 1 < len(ents) else e
    raw = d[BASE + e:BASE + nxt]
    if COMPRESSED[t] and raw[:2] == b'\x1f\x8b':
        return zlib.decompress(raw, 31)
    return raw
