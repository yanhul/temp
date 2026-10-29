#!/usr/bin/env python3
"""Giai doan A: trich xuat du lieu tho tu 1 trang PDF (vector + text).

TU DONG PHAT HIEN (khong hardcode mau):
  - Wire: tim cap (mau, do but) co NHIEU OBJECT POLYLINE (>=2 doan, kich thuoc
    >4pt) nhat — day mach trong Altium luon la polyline nhieu khuc; graphic
    linh kien la doan don / rect. Ho mau (family) = cung vi tri kenh mau manh
    nhat + cac kenh con lai bang 0 (vd xanh: (0,0,1) va (0,0,0.502) cung loai)
  - Junction: curve nho (<1.5pt) thuoc ho mau wire
  - Body: rect co mau nen non-trang pho bien nhat
  - Stub: duong don (LTLine) cung do but wire, dai <=25pt, mau bat ky;
    real = (mau stub == mau wire) — stub mau wire = manh day that, mau khac =
    chan linh kien / graphic
He toa do: PDF pt, goc duoi-trai, y-huong-len.
"""
import math
import re
import subprocess
import statistics
from collections import Counter, defaultdict
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTLine, LTRect, LTCurve, LTTextLine, LTTextContainer, LAParams, LTChar

RE_POPPLE_WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')


def _poppler_words(pdf, page_no, page_h):
    import html
    try:
        r = subprocess.run(['pdftotext', '-bbox', '-f', str(page_no + 1),
                            '-l', str(page_no + 1), pdf, '-'],
                           capture_output=True, text=True, timeout=120)
        out = []
        for m in RE_POPPLE_WORD.finditer(r.stdout):
            x0, y0, x1, y1 = (float(m.group(i)) for i in range(1, 5))
            txt = html.unescape(m.group(5)).strip()
            if txt:
                out.append((txt, (x0 + x1) / 2, page_h - (y0 + y1) / 2, True))
        return out
    except Exception:
        return []


def _norm(col):
    if col is None:
        return None
    if isinstance(col, (tuple, list)):
        return tuple(round(float(c), 3) for c in col)
    return (round(float(col), 3),)


def _emit_token(chars, out):
    text = ''.join(c.get_text() for c in chars)
    if not text:
        return
    x0 = min(c.bbox[0] for c in chars)
    x1 = max(c.bbox[2] for c in chars)
    y0 = min(c.bbox[1] for c in chars)
    y1 = max(c.bbox[3] for c in chars)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    char_pos = [(c.get_text(), c.bbox[0]) for c in chars]
    out['tokens'].append((text, cx, cy, char_pos))


def _emit_tokens_from_line(chars, out):
    cur = []
    prev_x1 = None
    for c in chars:
        ch = c.get_text()
        if ch.isspace():
            if cur:
                _emit_token(cur, out)
                cur = []
            prev_x1 = None
            continue
        if cur and prev_x1 is not None:
            gap = c.bbox[0] - prev_x1
            cw = c.bbox[2] - c.bbox[0]
            if gap > max(2.0, cw * 1.5):
                _emit_token(cur, out)
                cur = []
        cur.append(c)
        prev_x1 = c.bbox[2]
    if cur:
        _emit_token(cur, out)


def _walk(obj, out):
    if isinstance(obj, LTRect):
        fc = _norm(obj.non_stroking_color)
        if fc is not None:
            out['rects'].append((obj.bbox, fc))
    elif isinstance(obj, (LTLine, LTCurve)):
        sc = _norm(obj.stroking_color)
        if sc is not None:
            pts = getattr(obj, 'pts', None) or []
            x0, y0, x1, y1 = obj.bbox
            ext = max(x1 - x0, y1 - y0)
            out['objs'].append({'col': sc, 'w': round(obj.linewidth or 0, 3),
                                'pts': pts, 'ext': ext,
                                'is_line': isinstance(obj, LTLine)})
            if ext < 1.5:
                out['dots'].append(((x0 + x1) / 2, (y0 + y1) / 2, sc))
    elif isinstance(obj, LTTextContainer):
        # Process each line once here; avoid recursive duplicate text/token emission.
        for tl in obj:
            if isinstance(tl, LTTextLine):
                t = tl.get_text().strip()
                if t:
                    x0, y0, x1, y1 = tl.bbox
                    out['texts'].append((t, (x0 + x1) / 2, (y0 + y1) / 2,
                                         len(t.split()) == 1))
                chars = [c for c in tl if isinstance(c, LTChar)]
                if chars:
                    _emit_tokens_from_line(chars, out)
        return
    if hasattr(obj, '__iter__'):
        for ch in obj:
            try:
                _walk(ch, out)
            except Exception:
                pass


def _dominant_pattern(col):
    if len(col) == 3:
        mx = max(range(3), key=lambda i: col[i])
        zeros = tuple(1 if (i != mx and col[i] > 0.05) else 0 for i in range(3))
        return (mx, zeros)
    return ('gray', ())


def _same_family(c1, c2):
    return _dominant_pattern(c1) == _dominant_pattern(c2)


def extract_page(pdf, page_no=0):
    out = {'texts': [], 'objs': [], 'dots': [], 'rects': [], 'tokens': []}
    page_h = 612.0
    for i, page in enumerate(extract_pages(pdf, laparams=LAParams())):
        if i != page_no:
            continue
        page_h = page.bbox[3]
        for el in page:
            _walk(el, out)
        break
    out['label_texts'] = out['texts'] + _poppler_words(pdf, page_no, page_h)

    combo = defaultdict(lambda: {'multi': 0, 'segs': 0})
    for o in out['objs']:
        k = (o['col'], o['w'])
        nseg = max(0, len(o['pts']) - 1)
        if nseg >= 2 and o['ext'] > 4:
            combo[k]['multi'] += 1
            combo[k]['segs'] += nseg
    wire_col, wire_w = (None, 0.24)
    if combo:
        (wire_col, wire_w), _ = max(combo.items(), key=lambda kv: (kv[1]['multi'], kv[1]['segs']))

    fam = []
    for o in out['objs']:
        if o['w'] == wire_w and o['col'] and _same_family(o['col'], wire_col):
            fam.append(o)

    wire_segs = []
    for o in fam:
        if o['ext'] > 1.6 and len(o['pts']) >= 2:
            for i in range(len(o['pts']) - 1):
                wire_segs.append((o['pts'][i], o['pts'][i + 1]))

    junctions_exact = [(x, y) for (x, y, c) in out['dots'] if c == wire_col]
    junctions_fam = [(x, y) for (x, y, c) in out['dots']
                     if c and c != wire_col and wire_col and _same_family(c, wire_col)]

    stubs = []
    for o in out['objs']:
        if o['is_line'] and o['w'] == wire_w and o['ext'] <= 25 and len(o['pts']) >= 2:
            stubs.append((o['pts'][0], o['pts'][-1], o['col'] == wire_col))

    body_cols = Counter(fc for _, fc in out['rects']
                        if not (len(fc) == 3 and fc[0] > 0.92 and fc[1] > 0.92 and fc[2] > 0.92)
                        and not all(v < 0.08 for v in fc))
    body_col = body_cols.most_common(1)[0][0] if body_cols else None
    bodies = [bb for bb, fc in out['rects'] if fc == body_col] if body_col else []

    out.update({'wire_color': wire_col, 'wire_width': wire_w,
                'wire_segs': wire_segs, 'junctions': junctions_exact,
                'junctions_family': junctions_fam,
                'stubs': stubs, 'bodies': bodies, 'body_color': body_col})
    return out


def page_size(pdf, page_no=0):
    for i, page in enumerate(extract_pages(pdf, laparams=LAParams())):
        if i == page_no:
            return page.bbox[2], page.bbox[3]
    return 792.0, 612.0
