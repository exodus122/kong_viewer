"""Map wall triangles (pointer table 2), as loaded by func_global_asm_8066C958:
  u32 (stored in D_global_asm_807FB530), then blocks: u32 offset of the next block (from file start)
  followed by 0x18-byte walls: s16 x,y,z * 3, u16 facing (+0x12), u8 flags +0x14/+0x15/+0x16, pad.
The file is gzip-compressed for some maps.
"""
import struct, zlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptr

def load_walls(map_index):
    f = ptr.get_file(2, map_index)
    if f[:2] == b'\x1f\x8b':
        f = zlib.decompressobj(31).decompress(f)
    walls = []
    o = 4
    while o + 4 <= len(f):
        nxt = struct.unpack_from('>I', f, o)[0]
        if nxt <= o or nxt > len(f): break
        q = o + 4
        while q + 0x18 <= nxt:
            v = struct.unpack_from('>9h', f, q)
            walls.append((v, struct.unpack_from('>H', f, q + 0x12)[0], f[q + 0x14], f[q + 0x15], f[q + 0x16]))
            q += 0x18
        o = nxt
    return walls

if __name__ == '__main__':
    m = int(sys.argv[1], 0)
    w = load_walls(m)
    print(len(w), 'walls; first:', w[:3])
