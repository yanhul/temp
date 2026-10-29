#!/usr/bin/env python3
"""Export pad/net/snap diagnostics to CSV for manual comparison with the source PDF."""
import csv, os, sys
from pdfx import extract_page, page_size
from padsx import decode_pads
from netsx import build_netlist

def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: python dump_debug.py input.pdf [outdir]')
    pdf = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else 'debug'
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf))[0]
    pg = extract_page(pdf, 0)
    pg['page_h'] = page_size(pdf, 0)[1]
    padpos, _a, _b, _unresolved, _ambiguous = decode_pads(pg['texts'], tokens=pg.get('tokens'))
    netres = build_netlist(pg, padpos, pg['texts'])
    padpos = netres['padpos']
    with open(os.path.join(outdir, f'{base}_pads.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['pad','x','y','status'])
        attached, unattached, ambiguous = set(netres['attached_pads']), set(netres['unattached_pads']), set(netres['ambiguous_pads'])
        for k, (x,y) in sorted(padpos.items()):
            status = 'attached' if k in attached else 'unattached' if k in unattached else 'ambiguous' if k in ambiguous else 'unknown'
            w.writerow([k, round(x,2), round(y,2), status])
    with open(os.path.join(outdir, f'{base}_nets.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['net','pads','labels'])
        for name, info in sorted(netres['nets'].items()):
            w.writerow([name, ' '.join(info['pads']), ' '.join(info['labels'])])
    with open(os.path.join(outdir, f'{base}_snaps.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['pad','orig_x','orig_y','snap_x','snap_y','dist'])
        for k, (ox,oy), (nx,ny), d in netres['snap_moves']:
            w.writerow([k,ox,oy,nx,ny,d])
    print(f'wrote {outdir}/{base}_*.csv')
    print(f"pads: {len(padpos)} nets: {len(netres['nets'])}; attached={len(netres['attached_pads'])} unattached={len(netres['unattached_pads'])} ambiguous={len(netres['ambiguous_pads'])}")
if __name__ == '__main__': main()
