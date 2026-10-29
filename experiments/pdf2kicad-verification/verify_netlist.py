#!/usr/bin/env python3
"""Compare KiCad exported netlist with ground-truth CSV; net names are ignored."""
import csv, re, shutil, subprocess, sys, tempfile, os

def balanced_forms(text, token='(net'):
    pos = 0
    while True:
        start = text.find(token, pos)
        if start < 0: return
        after = start + len(token)
        if ((start and (text[start-1].isalnum() or text[start-1] in '_-')) or (after < len(text) and not text[after].isspace() and text[after] != ')')):
            pos = start + len(token); continue
        depth = 0; quoted = escaped = False
        for end in range(start, len(text)):
            ch = text[end]
            if quoted:
                if escaped: escaped = False
                elif ch == '\\': escaped = True
                elif ch == '"': quoted = False
            else:
                if ch == '"': quoted = True
                elif ch == '(': depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        yield text[start:end+1]; pos = end+1; break
        else: return

def main():
    if len(sys.argv) < 3: raise SystemExit('usage: python verify_netlist.py file.kicad_sch ground_truth.csv')
    sch, gt_csv = sys.argv[1:3]
    if not shutil.which('kicad-cli'): raise SystemExit('ERROR: kicad-cli not found')
    fd, netpath = tempfile.mkstemp(suffix='.net'); os.close(fd)
    try:
        r = subprocess.run(['kicad-cli','sch','export','netlist','--format','kicadsexpr','-o',netpath,sch], capture_output=True, text=True)
        if r.returncode: raise SystemExit(f'ERROR: kicad-cli failed ({r.returncode}): {r.stderr.strip()}')
        text = open(netpath, encoding='utf-8').read()
    finally:
        try: os.unlink(netpath)
        except OSError: pass
    actual = set()
    for form in balanced_forms(text):
        if not re.search(r'\(name\s+"((?:\\.|[^"])*)"\)', form): continue
        pins = set()
        for node in balanced_forms(form, '(node'):
            ref = re.search(r'\(ref\s+"((?:\\.|[^"])*)"\)', node)
            pin = re.search(r'\(pin\s+"((?:\\.|[^"])*)"\)', node)
            if ref and pin: pins.add(f'{ref.group(1)}.{pin.group(1)}')
        if pins: actual.add(frozenset(pins))
    expected = set()
    with open(gt_csv, newline='', encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].lstrip().startswith('#') or row[0].strip().lower() in {'net','net_name','name'}: continue
            pins = frozenset(p.strip() for p in row[1:] if p.strip())
            if pins: expected.add(pins)
    if not expected: raise SystemExit('ERROR: ground-truth CSV contains no nets with pins')
    missing, extra = expected-actual, actual-expected
    print(f'ground-truth={len(expected)} actual={len(actual)} missing={len(missing)} extra={len(extra)}')
    for title, sets in (('MISSING',missing),('EXTRA',extra)):
        for pins in sorted(sets, key=lambda x: sorted(x))[:20]: print(title + ': ' + ', '.join(sorted(pins)))
    raise SystemExit(0 if not missing and not extra else 2)
if __name__ == '__main__': main()
