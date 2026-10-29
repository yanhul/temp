#!/usr/bin/env python3
"""pdf2kicad_generic — PDF schematic (Altium) -> KiCad 9 (DRAFT, strict mode)."""
import os, sys, glob, argparse, json
from pdfx import extract_page, page_size
from padsx import decode_pads
from netsx import build_netlist
from gen import gen_page

RE_SHEET_HINT = 12


def main():
    ap = argparse.ArgumentParser(description='PDF schematic -> KiCad 9 (generic DRAFT)')
    ap.add_argument('pdf')
    ap.add_argument('-o', '--out', default='out_kicad')
    ap.add_argument('--pages', default='')
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f'khong tim thay file: {args.pdf}')
    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.pdf))[0]

    try:
        import pypdf
        npages = len(pypdf.PdfReader(args.pdf).pages)
    except Exception:
        r = os.popen(f'pdfinfo "{args.pdf}" 2>/dev/null | grep -i "^Pages"').read()
        npages = int(r.split(':')[1]) if ':' in r else 1

    want = set()
    if args.pages:
        want = {int(p) - 1 for p in args.pages.split(',') if p.strip().isdigit()}

    pages = []
    for i in range(npages):
        if want and i not in want:
            continue
        pg = extract_page(args.pdf, i)
        n_pad_tok = sum(1 for t, x, y, st in pg['texts'] if t.startswith('PI'))
        w, h = page_size(args.pdf, i)
        pg['page_h'] = h
        pg['page_w'] = w
        pg['n_pad_tok'] = n_pad_tok
        if n_pad_tok >= RE_SHEET_HINT and len(pg['objs']) > 20:
            pages.append((i, pg))
            print(f'  trang {i+1}: SCHEMATIC ({n_pad_tok} PI, {len(pg["objs"])} object)')
        else:
            print(f'  trang {i+1}: bo qua ({n_pad_tok} PI, {len(pg["objs"])} object)')
    if not pages:
        sys.exit('khong tim thay trang schematic nao (thu --pages 1)')

    all_pads = {}
    all_nets = []
    per_page = {}
    for i, pg in pages:
        print(f'— trang {i+1}: giai ma pad...')
        padpos, refs_found, refs_unseen, unresolved, ambiguous = decode_pads(
            pg['texts'], tokens=pg.get('tokens'))
        print(f'  refs: {len(refs_found)}  pads: {len(padpos)}'
              f'  unresolved: {len(unresolved)}  ambiguous: {len(ambiguous)}')
        if ambiguous:
            for i_, pool, xy in ambiguous[:3]:
                print(f'    AMBIGUOUS @ {xy}: {[r for r, _ in pool]}')

        # Sanity check wire detection (heuristic only; not proof of correct color).
        n_w = len(pg.get('wire_segs', []))
        if padpos and n_w > 0:
            ratio = n_w / len(padpos)
            if ratio < 0.1 or ratio > 20:
                print(f'  CANH BAO: wire/pad ratio={ratio:.2f} bat thuong'
                      f' (wire={n_w}, pad={len(padpos)}) — co the chon sai mau wire')

        netres = build_netlist(pg, padpos, pg['texts'])
        padpos = netres['padpos']
        n_a = len(netres['attached_pads'])
        n_u = len(netres['unattached_pads'])
        n_m = len(netres['ambiguous_pads'])
        n_dt = len(netres['dangling_tjunctions'])
        n_sn = len(netres['snap_moves'])
        n_sr = len(netres.get('snap_refused', []))
        print(f'  nets: {len(netres["nets"])}  wires: {len(netres["wires"])}')
        print(f'  pads: attached={n_a} unattached={n_u} ambiguous={n_m}'
              f'  (tong {n_a+n_u+n_m}/{len(padpos)})')
        if n_dt: print(f'  CANH BAO: {n_dt} T-junction khong co dot (khong tu noi)')
        if netres.get('mid_seg_attach'):
            print(f'  CANH BAO: {len(netres["mid_seg_attach"])} pad tren than seg')
        if n_sn: print(f'  INFO: snap {n_sn} padpos sang stub endpoint')
        if n_sr: print(f'  CANH BAO: tu choi snap {n_sr} vi refdes mismatch')
        per_page[i] = (pg, padpos, netres)
        all_pads.update(padpos)
        all_nets.append(netres)

    name_pages = {}
    for i, (pg, padpos, netres) in per_page.items():
        for root, nm in netres['root_name'].items():
            name_pages.setdefault(nm, set()).add(i)
    multi = {nm for nm, ss in name_pages.items() if len(ss) > 1}

    files = []
    if len(pages) == 1:
        i, (pg, padpos, netres) = list(per_page.items())[0]
        netres['multi_page_nets'] = multi
        fn, fu, syms = gen_page(base, i, pg, padpos, netres, args.out,
                                fname=f'{base}.kicad_sch')
        files.append(fn)
        n_comp = len(syms)
    else:
        from kcx import uid as _kcx_uid, esc
        root_uuid = _kcx_uid()
        children = []
        for k, (i, (pg, padpos, netres)) in enumerate(sorted(per_page.items())):
            netres['multi_page_nets'] = multi
            su = __import__('uuid').uuid4()
            fn, fu, syms = gen_page(base, i, pg, padpos, netres, args.out,
                                    inst_path=f'/{root_uuid}/{su}',
                                    fname=f'{base}_p{i+1}.kicad_sch')
            files.append(fn)
            children.append((i, fn, su, fu, syms))
        sheets_el = []
        for k, (i, fn, su, fu, _syms) in enumerate(children):
            x, y = 30 + (k % 4) * 120, 30 + (k // 4) * 70
            sheets_el.append(
                f'\t(sheet (at {x} {y}) (size 100 50) (exclude_from_sim no) (in_bom yes) (on_board yes) '
                f'(fields_autoplaced yes)\n\t\t(stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000))\n'
                f'\t\t(uuid "{su}")\n'
                f'\t\t(property "Sheetname" "Page_{i+1}" (at {x} {y-1.27} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
                f'\t\t(property "Sheetfile" "{fn}" (at {x} {y+51.27} 0) (effects (font (size 1.27 1.27)) (justify left top)))\n'
                f'\t\t(instances (project "{esc(base)}" (path "/{root_uuid}" (page "{k+2}"))))\n\t)')
        root = ('(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n'
                f'\t(uuid "{root_uuid}")\n\t(paper "A3")\n\t(title_block\n\t\t(title "{esc(base)} DRAFT")\n'
                '\t\t(date "")\n\t\t(rev "DRAFT")\n\t\t(company "pdf2kicad_generic")\n'
                '\t\t(comment 1 "AUTO-CONVERTED DRAFT — xem report.txt")\n\t)\n'
                '\t(lib_symbols\n\t)\n' + '\n'.join(sheets_el) +
                '\n\t(sheet_instances\n\t\t(path "/" (page "1"))\n\t)\n\t(embedded_fonts no)\n)\n')
        with open(os.path.join(args.out, f'{base}.kicad_sch'), 'w') as f:
            f.write(root)
        files.append(f'{base}.kicad_sch')
        n_comp = sum(len(c[4]) for c in children)

    pro = {'board': {}, 'meta': {'filename': f'{base}.kicad_pro', 'version': 3},
           'schematic': {'legacy_lib_dir': '', 'legacy_lib_list': [],
                         'meta': {'version': 3}, 'net_format_version': 2,
                         'page_layout_descr_file': ''},
           'sheets': [[None, 'Root']],
           'libraries': {'pinned_footprint_libs': [], 'pinned_symbol_libs': []},
           'text_variables': {}}
    import re as _re
    root_file = f'{base}.kicad_sch'
    mu = _re.search(r'\(uuid "([0-9a-f-]+)"\)', open(os.path.join(args.out, root_file)).read())
    if mu:
        pro['sheets'] = [[mu.group(1), 'Root']]
    with open(os.path.join(args.out, f'{base}.kicad_pro'), 'w') as f:
        json.dump(pro, f, indent=2)

    # Report canh bao
    lines = [f'{base} — DRAFT auto-conversion report', '=' * 60, '']
    for i, (pg, padpos, netres) in per_page.items():
        lines.append(f'Page {i+1}:')
        lines.append(f'  Pads attached  : {len(netres["attached_pads"])}')
        lines.append(f'  Pads unattached: {len(netres["unattached_pads"])}')
        for k in netres['unattached_pads']:
            lines.append(f'    UNATTACHED: {k}')
        lines.append(f'  Pads ambiguous : {len(netres["ambiguous_pads"])}')
        for k in netres['ambiguous_pads']:
            lines.append(f'    AMBIGUOUS: {k}')
        if netres.get('mid_seg_attach'):
            lines.append(f'  Pad tren than seg (khong co dot): {len(netres["mid_seg_attach"])}')
            for k, x, y, d in netres['mid_seg_attach'][:20]:
                lines.append(f'    MID-ATTACH: {k} @ ({x},{y}) d={d}')
        if netres.get('snap_refused'):
            lines.append(f'  Snap bi tu choi (refdes mismatch): {len(netres["snap_refused"])}')
            for k, end, refs in netres['snap_refused'][:10]:
                lines.append(f'    REFUSE-SNAP: {k} -> {end} (stub gan refs {refs})')
        if netres['snap_moves']:
            lines.append(f'  Snap padpos -> stub endpoint: {len(netres["snap_moves"])}')
            for k, old, new, d in netres['snap_moves'][:10]:
                lines.append(f'    {k}: {old} -> {new} (d={d})')
        if netres['dangling_tjunctions']:
            lines.append(f'  T-junctions khong co dot (KHONG tu noi): {len(netres["dangling_tjunctions"])}')
            for xy in netres['dangling_tjunctions'][:20]:
                lines.append(f'    @ {xy}')
        lines.append('')
    lines.append('KHONG dung schematic nay de san xuat PCB truoc khi:')
    lines.append('  1. Chay ERC trong KiCad')
    lines.append('  2. Soat lai tat ca UNATTACHED + AMBIGUOUS o tren')
    lines.append('  3. So sanh netlist voi PDF goc')
    with open(os.path.join(args.out, 'report.txt'), 'w') as f:
        f.write('\n'.join(lines))

    n_pads = len(all_pads)
    n_nets = sum(len(n['nets']) for _, _, n in per_page.values())
    for i, (_pg, _padpos, netres) in per_page.items():
        if netres.get('mid_seg_attach'):
            print(f'  CANH BAO trang {i+1}: {len(netres["mid_seg_attach"])} pad nam TREN than seg (khong co dot)')
    print(f'\n=== XONG (DRAFT): {args.out}/ ===')
    print(f'  linh kien: {n_comp}   pad: {n_pads}   net: {n_nets}   file: {len(files)}')
    print(f'  report canh bao: {args.out}/report.txt')
    print(f'  Mo {base}.kicad_sch bang KiCad 9 — nhung day la DRAFT, phai verify.')


if __name__ == '__main__':
    main()
