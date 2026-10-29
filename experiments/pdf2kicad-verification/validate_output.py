#!/usr/bin/env python3
"""Kiem tra file .kicad_sch. KHONG claim 'PARSE OK = dung'.
Exit code: 0 = syntax ok; 1 = parse error; 2 = co canh bao dien hoc.
"""
import sys, os, glob
from collections import Counter
from kiutils.schematic import Schematic

target = sys.argv[1] if len(sys.argv) > 1 else 'out_kicad'
files = (sorted(glob.glob(os.path.join(target, '*.kicad_sch')))
         if os.path.isdir(target) else [target])
if not files:
    sys.exit(f'khong thay .kicad_sch nao trong {target}')


def count_wires(s):
    """Dem doi tuong Wire that, khong dem graphical items khac."""
    n = 0
    for g in s.graphicalItems:
        if type(g).__name__ == 'Wire':
            n += 1
    return n


syms, refs, pwr = Counter(), set(), Counter()
labels, glabels, wires, ncs, juncs, errs = 0, 0, 0, 0, 0, []
for f in files:
    try:
        s = Schematic.from_file(f)
    except Exception as e:
        errs.append(f'{os.path.basename(f)}: {e}')
        continue
    name = os.path.basename(f)
    for sym in s.schematicSymbols:
        ref = next((p.value for p in sym.properties if p.key == 'Reference'), '?')
        if ref.startswith('#'):
            pwr[next((p.value for p in sym.properties if p.key == 'Value'), '?')] += 1
        else:
            refs.add(ref)
            syms[name] += 1
    labels += len(s.labels)
    glabels += len(s.globalLabels)
    wires += count_wires(s)
    ncs += len(s.noConnects)
    juncs += len(s.junctions)

print(f'muc tieu   : {target}')
print(f'so file    : {len(files)}')
print(f'linh kien  : {sum(syms.values())} instance / {len(refs)} refdes')
print(f'label      : {labels} local + {glabels} global')
print(f'wire       : {wires}   junction: {juncs}   no_connect: {ncs}')
print(f'power sym  : {sum(pwr.values())} '
      f'({", ".join(f"{k}x{v}" for k, v in sorted(pwr.items()))})')

warns = []
if ncs > 0:
    warns.append(f'{ncs} no_connect ton tai (KHONG nen co — NC gia)')
if wires == 0 and sum(syms.values()) > 0:
    warns.append('0 wire nhung co symbol — netlist chac chan sai')

import shutil, subprocess, tempfile
if shutil.which('kicad-cli') and len(files) == 1:
    try:
        with tempfile.NamedTemporaryFile(suffix='.net', delete=False) as tf:
            netpath = tf.name
        r = subprocess.run(
            ['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr',
             '-o', netpath, files[0]],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            with open(netpath) as fh:
                net_txt = fh.read()
            n_net = net_txt.count('(net ')
            n_node = net_txt.count('(node ')
            print(f'netlist    : {n_net} net / {n_node} node (kicad-cli)')
            os.unlink(netpath)
        else:
            warns.append(f'kicad-cli netlist fail: {r.stderr.strip()[:120]}')
    except Exception as e:
        warns.append(f'kicad-cli exception: {e}')
else:
    warns.append('kicad-cli khong co — chua chay ERC/netlist export duoc')

if warns:
    print('\nCANH BAO:')
    for w in warns:
        print(f'  ! {w}')

if errs:
    print('\nLOI PARSE:')
    for e in errs:
        print(f'  {e}')
    sys.exit(1)

if warns:
    print('\nKet luan: cu phap OK, nhung CHUA xac minh dien hoc. Xem report.txt.')
    sys.exit(2)
print('\nPARSE OK (chi cu phap — KHONG chung minh dung dien hoc)')
