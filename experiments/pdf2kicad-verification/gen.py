#!/usr/bin/env python3
"""Giai doan D: chieu hinh hoc -> .kicad_sch KiCad 9.

DRAFT MODE:
  - Header title_block co comment canh bao + rev="DRAFT" + date rong.
  - KHONG sinh no_connect tu unattached (day la false-positive nguy hiem).
"""
import os, math
from collections import defaultdict
from kcx import (PT2MM, PAPERS, MARGIN, RE_POWER, RE_GND, uid, fnum, esc,
                 sym_power, sym_pwr_flag, sym_box)


def pick_transform(contents):
    xs = [x * PT2MM for x, y in contents]
    ys = [y * PT2MM for x, y in contents]
    w = (max(xs) - min(xs)) if xs else 100.0
    h = (max(ys) - min(ys)) if ys else 100.0
    for name, (pw, ph) in PAPERS.items():
        aw, ah = pw - 2 * MARGIN, ph - 2 * MARGIN
        s = min(1.0, aw / w, ah / h)
        if w * s <= aw + 0.5 and h * s <= ah + 0.5:
            return name, s, min(xs), min(ys)
    (name, (pw, ph)) = list(PAPERS.items())[-1]
    s = min((pw - 2 * MARGIN) / w, (ph - 2 * MARGIN) / h)
    return name, s, min(xs), min(ys)


def value_for(ref, texts, bbox):
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    best, bd = None, 1e9
    for t, tx, ty, st in texts:
        tt = t.strip()
        if not tt or tt.upper() == ref or tt.startswith('PI') or len(tt) > 32:
            continue
        if x0 - 8 <= tx <= x1 + 8 and y0 - 8 <= ty <= y1 + 8:
            d = math.hypot(tx - cx, ty - cy)
            if d < bd:
                best, bd = tt, d
    return best or ref


def gen_page(pdfbase, page_no, page, padpos, netres, out_dir,
             inst_path=None, fname=None, multi_page_nets=()):
    wires, stubs, uf = netres['wires'], netres['stubs'], netres['uf']
    anchors = netres['anchors']
    root_name = netres['root_name']
    root_pads = netres['root_pads']
    page_h = page.get('page_h', 612.0)

    def kp(p):
        return ('P', round(p[0], 2), round(p[1], 2))

    roots_with_pad = {uf.find(('PAD', k)) for k in padpos}
    draw_wires = [w for w in wires if uf.find(kp(w[0])) in roots_with_pad]
    draw_stubs = [s for s in stubs
                  if uf.find(kp(s[0])) in roots_with_pad or uf.find(kp(s[1])) in roots_with_pad]

    pts = [p for w in draw_wires + draw_stubs for p in w] + list(padpos.values())
    paper, s, x0mm, _ = pick_transform(pts)
    ox = MARGIN - x0mm * s

    def T(x, y):
        return (round(x * PT2MM * s + ox, 3), round((page_h - y) * PT2MM * s + MARGIN, 3))

    def TW(seg):
        return (T(*seg[0]), T(*seg[1]))

    comp_pads = defaultdict(list)
    for k, (x, y) in padpos.items():
        ref, pad = k.split('.', 1)
        comp_pads[ref].append((pad, x, y))
    symbols = {}
    for ref, pads in sorted(comp_pads.items()):
        xs = [p[1] for p in pads]; ys = [p[2] for p in pads]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        TX, TY = T(cx, cy)
        rel = []
        for num, wx, wy in pads:
            WX, WY = T(wx, wy)
            rel.append((num, round(WX - TX, 3), round(TY - WY, 3)))
        symbols[ref] = {'x': TX, 'y': TY, 'pads': rel,
                        'value': value_for(ref, page['texts'], bbox)}

    pad_net = {}
    for root, pads in root_pads.items():
        nm = root_name.get(root) or ('N_' + pads[0].replace('.', '_'))
        for p in pads:
            pad_net[p] = nm
    power_nets = {nm for nm in set(root_name.values())
                  if RE_POWER.match(nm or '') and not (nm or '').startswith('N_')}

    libs = [sym_pwr_flag()]
    for ref, sy in sorted(symbols.items()):
        libs.append(sym_box(ref, sy['value'], sy['pads']))
    for nm in sorted(power_nets):
        libs.append(sym_power(nm, RE_GND.match(nm) is not None))

    el = []
    file_uuid = uid()
    inst = inst_path or f'/{file_uuid}'

    for a, b in [TW(w) for w in draw_wires] + [TW(s_) for s_ in draw_stubs]:
        el.append(f'\t(wire (pts (xy {fnum(a[0])} {fnum(a[1])}) (xy {fnum(b[0])} {fnum(b[1])})) '
                  f'(stroke (width 0) (type default)) (uuid "{uid()}"))')
    all_juncs = {(round(x, 1), round(y, 1))
                 for x, y in list(page['junctions']) + list(page.get('junctions_family', []))}
    for (jx, jy) in sorted(all_juncs):
        X, Y = T(jx, jy)
        el.append(f'\t(junction (at {fnum(X)} {fnum(Y)} 0) (diameter 0) (color 0 0 0 0) (uuid "{uid()}"))')

    pwr_i = [0]; flg_i = [0]
    def next_pwr():
        pwr_i[0] += 1
        return f'#PWR{pwr_i[0]:02d}'
    def next_flg():
        flg_i[0] += 1
        return f'#FLG{flg_i[0]:02d}'

    def add_flag(X, Y):
        FX, FY = X + 7.62, Y
        el.append(f'\t(wire (pts (xy {fnum(X)} {fnum(Y)}) (xy {fnum(FX)} {fnum(FY)})) '
                  f'(stroke (width 0) (type default)) (uuid "{uid()}"))')
        r = next_flg()
        el.append('\t(symbol (lib_id "power:PWR_FLAG") (at %s %s 0) (unit 1)\n'
                  '\t\t(exclude_from_sim no) (in_bom no) (on_board yes) (dnp no)\n'
                  '\t\t(uuid "%s")\n'
                  '\t\t(property "Reference" "%s" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  '\t\t(property "Value" "PWR_FLAG" (at %s %s 0) (effects (font (size 1.27 1.27))))\n'
                  '\t\t(property "Footprint" "" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  '\t\t(property "Datasheet" "~" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  '\t\t(property "Description" "Power flag" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  '\t\t(pin "1" (uuid "%s"))\n'
                  '\t\t(instances (project "%s" (path "%s" (reference "%s") (unit 1))))\n\t)'
                  % (fnum(FX), fnum(FY), uid(), r, fnum(FX), fnum(FY - 3),
                     fnum(FX), fnum(FY + 3), fnum(FX), fnum(FY), fnum(FX), fnum(FY),
                     fnum(FX), fnum(FY), uid(), esc(pdfbase), esc(inst), r))

    flag_done = set()
    for root, ls in sorted(anchors.items(), key=lambda kv: str(kv[1][0][1])):
        pads = root_pads.get(root)
        if not pads:
            continue
        nm = root_name.get(root)
        if not nm:
            continue
        is_pwr = nm in power_nets
        for (t, ax, ay) in ls:
            X, Y = T(ax, ay)
            if is_pwr:
                gnd = RE_GND.match(nm) is not None
                r = next_pwr()
                vy = Y + (-5.6 if gnd else 5.2)
                el.append('\t(symbol (lib_id "power:%s") (at %s %s 0) (unit 1)\n'
                          '\t\t(exclude_from_sim no) (in_bom no) (on_board yes) (dnp no)\n'
                          '\t\t(uuid "%s")\n'
                          '\t\t(property "Reference" "%s" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                          '\t\t(property "Value" "%s" (at %s %s 0) (effects (font (size 1.27 1.27))))\n'
                          '\t\t(property "Footprint" "" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                          '\t\t(property "Datasheet" "~" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                          '\t\t(property "Description" "Power symbol" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                          '\t\t(pin "1" (uuid "%s"))\n'
                          '\t\t(instances (project "%s" (path "%s" (reference "%s") (unit 1))))\n\t)'
                          % (esc(nm), fnum(X), fnum(Y), uid(), r, fnum(X), fnum(Y),
                             esc(nm), fnum(X), fnum(vy), fnum(X), fnum(Y),
                             fnum(X), fnum(Y), fnum(X), fnum(Y), uid(),
                             esc(pdfbase), esc(inst), r))
                if nm not in flag_done:
                    flag_done.add(nm)
                    add_flag(X, Y)
            else:
                if nm in multi_page_nets:
                    el.append(f'\t(global_label "{esc(nm)}" (shape input) (at {fnum(X)} {fnum(Y)} 0) (fields_autoplaced yes)\n'
                              f'\t\t(effects (font (size 1.27 1.27)) (justify left)) (uuid "{uid()}")\n'
                              f'\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {fnum(X)} {fnum(Y)} 0) '
                              f'(effects (font (size 1.27 1.27)) (hide yes))\n\t)')
                else:
                    el.append(f'\t(label "{esc(nm)}" (at {fnum(X)} {fnum(Y)} 0) '
                              f'(effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{uid()}"))')

    for ref, sy in sorted(symbols.items()):
        X, Y = sy['x'], sy['y']
        hmax = max((abs(dy) for _, _, dy in sy['pads']), default=3.0) + 3.0
        el.append('\t(symbol (lib_id "AUTO:%s") (at %s %s 0) (unit 1)\n'
                  '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
                  '\t\t(uuid "%s")\n'
                  '\t\t(property "Reference" "%s" (at %s %s 0) (effects (font (size 1.27 1.27))))\n'
                  '\t\t(property "Value" "%s" (at %s %s 0) (effects (font (size 1.27 1.27))))\n'
                  '\t\t(property "Footprint" "" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  '\t\t(property "Datasheet" "~" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  '\t\t(property "Description" "Auto from PDF page %d" (at %s %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                  % (esc(ref), fnum(X), fnum(Y), uid(),
                     esc(ref), fnum(X), fnum(Y - hmax),
                     esc(sy['value']), fnum(X), fnum(Y + hmax),
                     fnum(X), fnum(Y), fnum(X), fnum(Y),
                     page_no + 1, fnum(X), fnum(Y)))
        for num, _, _ in sy['pads']:
            el.append(f'\t\t(pin "{esc(num)}" (uuid "{uid()}"))')
        el.append(f'\t\t(instances (project "{esc(pdfbase)}" (path "{esc(inst)}" '
                  f'(reference "{esc(ref)}") (unit 1))))\n\t)')

    title = f'{pdfbase} — page {page_no + 1} (auto-converted DRAFT)'
    warn = "AUTO-CONVERTED DRAFT — topology heuristic, chua verify dien hoc"
    txt = ('(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n'
           f'\t(uuid "{file_uuid}")\n\t(paper "{paper}")\n\t(title_block\n\t\t(title "{esc(title)}")\n'
           '\t\t(date "")\n\t\t(rev "DRAFT")\n\t\t(company "pdf2kicad_generic")\n'
           f'\t\t(comment 1 "{esc(warn)}")\n'
           '\t\t(comment 2 "Xem report.txt — KHONG dung de san xuat truoc khi ERC + soat tay")\n\t)\n'
           '\t(lib_symbols\n' + '\n'.join(libs) + '\n\t)\n'
           + '\n'.join(el) +
           '\n\t(sheet_instances\n\t\t(path "/" (page "1"))\n\t)\n\t(embedded_fonts no)\n)\n')
    fname = fname or f'{pdfbase}_p{page_no + 1}.kicad_sch'
    with open(os.path.join(out_dir, fname), 'w') as f:
        f.write(txt)
    return fname, file_uuid, symbols
