"""Map animation types (playAnimation's 2nd arg) to player control states, by scanning the decomp:
a `control_state = X` (C) or `sb rN, 0x154(actor)` (asm) shortly before `playAnimation(actor, T)`.
Writes action_types.json: {type: [control_state, ...]}. Usage: python action_types.py [dk64 decomp root]"""
import collections, glob, json, os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
pairs = collections.defaultdict(collections.Counter)
direct = set()      # script indices the code starts directly with playActorAnimation

for path in glob.glob(os.path.join(ROOT, 'src', '**', '*.c'), recursive=True):
    # functions that set exactly one control state and play animations
    body, inside = [], False
    for ln in open(path, encoding='utf-8', errors='ignore'):
        if not inside and re.match(r'^[A-Za-z].*\)\s*\{\s*$', ln):
            inside, body = True, []
        elif inside and ln.startswith('}'):
            b = ''.join(body)
            states = set(int(x, 0) for x in re.findall(r'control_state\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;', b))
            if len(states) == 1:
                for t in re.findall(r'playAnimation\([^,]+,\s*(0x[0-9A-Fa-f]+|\d+)\)', b):
                    pairs[int(t, 0)][next(iter(states))] += 1
            inside = False
        elif inside:
            body.append(ln)
    # control_state assignment shortly before a playAnimation call
    last, age = None, 99
    for ln in open(path, encoding='utf-8', errors='ignore'):
        if re.match(r'^[A-Za-z].*\)\s*\{\s*$', ln): last, age = None, 99
        m = re.search(r'control_state\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;', ln)
        if m: last, age = int(m.group(1), 0), 0; continue
        age += 1
        m = re.search(r'playAnimation\([^,]+,\s*(0x[0-9A-Fa-f]+|\d+)\)', ln)
        if m and last is not None and age <= 8:
            pairs[int(m.group(1), 0)][last] += 1
        m = re.search(r'playActorAnimation\([^,]+,\s*(0x[0-9A-Fa-f]+|\d+)\)', ln)
        if m:
            direct.add(int(m.group(1), 0))
            if last is not None and age <= 8: pairs['s%d' % int(m.group(1), 0)][last] += 1

for path in glob.glob(os.path.join(ROOT, 'asm', 'nonmatchings', '**', '*.s'), recursive=True):
    regs, last, age = {}, None, 99
    for ln in open(path, encoding='utf-8', errors='ignore'):
        m = re.search(r'addiu\s+\$(\w+), \$zero, (0x[0-9A-F]+|\d+)', ln)
        if m: regs[m.group(1)] = int(m.group(2), 0)
        m = re.search(r'sb\s+\$(\w+), 0x154\(', ln)
        if m and m.group(1) in regs: last, age = regs[m.group(1)], 0; continue
        age += 1
        if 'jal' in ln and 'playAnimation' in ln and 'a1' in regs and last is not None and age <= 12:
            pairs[regs['a1']][last] += 1
        if 'jal' in ln and 'playActorAnimation' in ln and 'a1' in regs:
            direct.add(regs['a1'])
            if last is not None and age <= 12: pairs['s%d' % regs['a1']][last] += 1

out = {str(t): [s for s, _ in c.most_common()] for t, c in sorted(pairs.items(), key=lambda kv: str(kv[0]))}
out['direct_scripts'] = sorted(direct)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'action_types.json'), 'w'), indent=0)
print(len(out) - 1, 'entries,', len(direct), 'direct scripts')
