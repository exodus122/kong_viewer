"""Regenerate opcodes.json: argument length of each animation-script opcode (D_global_asm_80746BEC handlers),
derived from the decomp sources. Usage: python opcodes.py [path/to/dk64 decomp]"""
import re, os, sys, json
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
data = open(os.path.join(ROOT,'asm/data/global_asm/data_14B860.data.s')).read()
m = re.search(r'dlabel D_global_asm_80746BEC\n(.*?)\.size', data, re.S)
handlers = re.findall(r'\.word (\w+)', m.group(1))
csrc = open(os.path.join(ROOT,'src/global_asm/code_18750.c')).read()
bodies = {}
for fm in re.finditer(r'^[A-Za-z][^\n;]*?\b(func_global_asm_[0-9A-F]+)\([^\n;]*\)\s*\{\n(.*?)^\}', csrc, re.S | re.M):
    bodies[fm.group(1)] = fm.group(2)
out = []
for op, h in enumerate(handlers):
    body = bodies.get(h); src = 'c'
    if body is None:
        p = os.path.join(ROOT, 'asm/nonmatchings/global_asm/code_18750', h + '.s')
        body = open(p).read() if os.path.exists(p) else ''
        src = 'asm' if body else 'none'
    n8 = len(re.findall(r'getAnimationArg8\b', body)); n16 = len(re.findall(r'getAnimationArg16\b', body)); n32 = len(re.findall(r'getAnimationArg32\b', body))
    inc = len(re.findall(r'D_global_asm_807F5AF0\+\+', body))
    other = re.findall(r'D_global_asm_807F5AF0 *[+-]= *([^;]+);', body)
    setsanim = [c for c in ('func_global_asm_80613C48','func_global_asm_80613BA0','func_global_asm_80613CA8','func_global_asm_80613AF8','func_global_asm_80614014') if c in body]
    out.append(dict(op=op, h=h, src=src, n8=n8, n16=n16, n32=n32, inc=inc, other=other, setsanim=setsanim, length=inc + n8 + 2*n16 + 4*n32))
for o in out: print(o['op'], hex(o['op']), o['h'][16:], o['src'], 'inc', o['inc'], 'a8', o['n8'], 'a16', o['n16'], 'a32', o['n32'], 'oth', o['other'], 'anim' if o['setsanim'] else '', '=>', o['length'])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'opcodes.json'), 'w'), indent=1)
