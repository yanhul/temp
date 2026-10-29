#!/usr/bin/env python3
"""Giai doan C: do thi day mach -> netlist (STRICT MODE).

Nguyen tac: fail visible > silent wrong.
  - Chi noi khi co bang chung hinh hoc: endpoint trung <= TOL_ENDPOINT,
    hoac endpoint nam tren than seg khac + co junction dot <= TOL_JUNCTION.
  - Khong fallback "gan thi noi".
  - Pad: 3 trang thai ro rang (attached / unattached / ambiguous).
  - Khong sinh no_connect (gen.py khong dung unattached lam NC).
"""
import math, re
from collections import defaultdict, Counter

TOL_ENDPOINT    = 0.75
TOL_JUNCTION    = 1.2
TOL_PAD         = 1.0
TOL_SNAP_STUB   = 5.0
TOL_EXACT_MATCH = 0.1
TOL_TIE         = 0.3

PAD_TOKEN = re.compile(r'^PI')
_RE_REF = r'[A-Z]{1,4}\d{1,3}(?:_[A-Z0-9]{1,4})?'
RE_HIDDEN = re.compile(
    rf'^(?:PI{_RE_REF}0|NL{_RE_REF}(?![A-Za-z0-9])|CO{_RE_REF}(?![A-Za-z0-9]))'
)


def _dist_ps(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class UF:
    def __init__(self): self.p = {}
    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def build_netlist(page, padpos_in, texts, verbose=True):
    bodies = page['bodies']

    # ===== 1. Snap padpos -> stub graphic endpoint; verify nearby refdes =====
    stubs_norm = []
    for s in page['stubs']:
        if len(s) == 3:
            stubs_norm.append(s)
        else:
            a, b = s
            stubs_norm.append((a, b, True))

    graphic_stubs = [(a, b) for (a, b, rl) in stubs_norm if not rl]
    # Infer endpoint ownership only when one refdes is clearly nearest.
    # This is a guard, not proof: ambiguous endpoints remain unsnapped.
    graphic_end_with_stub = []
    endpoint_refdes = {}
    for idx, (a, b) in enumerate(graphic_stubs):
        for end_no, end in enumerate((a, b)):
            graphic_end_with_stub.append((end, idx, end_no))
            distances = sorted((math.hypot(end[0] - px, end[1] - py),
                                k.split('.')[0])
                               for k, (px, py) in padpos_in.items())
            if distances and distances[0][0] < 2 * TOL_SNAP_STUB:
                nearest_d = distances[0][0]
                nearest_refs = {ref for d, ref in distances
                                if d - nearest_d < 0.5}
                endpoint_refdes[(idx, end_no)] = (
                    next(iter(nearest_refs)) if len(nearest_refs) == 1 else None)
            else:
                endpoint_refdes[(idx, end_no)] = None

    padpos = {}
    snap_moves = []
    snap_refused = []
    for k, (x, y) in padpos_in.items():
        ref = k.split('.')[0]
        near = sorted(
            (math.hypot(ex - x, ey - y), (ex, ey), idx, end_no)
            for (ex, ey), idx, end_no in graphic_end_with_stub
            if math.hypot(ex - x, ey - y) < TOL_SNAP_STUB
        )
        if not near:
            padpos[k] = (x, y)
            continue
        if len(near) >= 2 and (near[1][0] - near[0][0]) < 0.5:
            padpos[k] = (x, y)
            continue
        d, end, stub_idx, end_no = near[0]
        nearest_ref = endpoint_refdes.get((stub_idx, end_no))
        if nearest_ref is not None and ref != nearest_ref:
            snap_refused.append((k, (round(end[0], 2), round(end[1], 2)),
                                 [nearest_ref]))
            padpos[k] = (x, y)
            continue
        padpos[k] = end
        if d > 0.15:
            snap_moves.append((k, (round(x, 2), round(y, 2)),
                               (round(end[0], 2), round(end[1], 2)), round(d, 2)))

    # ===== 2. Filter segs trong bbox symbol =====
    comp_pads = defaultdict(list)
    for k, (x, y) in padpos.items():
        comp_pads[k.split('.')[0]].append((x, y))
    keep = {}
    for ref, ps in comp_pads.items():
        xs = [p[0] for p in ps]; ys = [p[1] for p in ps]
        keep[ref] = (min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4)

    def seg_in_box(seg):
        (ax, ay), (bx, by) = seg
        x0, x1 = sorted((ax, bx)); y0, y1 = sorted((ay, by))
        for rx0, ry0, rx1, ry1 in keep.values():
            if x0 >= rx0 and x1 <= rx1 and y0 >= ry0 and y1 <= ry1:
                return True
        for bx0, by0, bx1, by1 in bodies:
            if x0 >= bx0 + 0.5 and x1 <= bx1 - 0.5 and y0 >= by0 + 0.5 and y1 <= by1 - 0.5:
                return True
        return False

    wires = [s for s in page['wire_segs'] if not seg_in_box(s)]

    if padpos:
        pts = list(padpos.values())
        stubs = [(a, b, rl) for (a, b, rl) in stubs_norm
                 if min(math.hypot(a[0]-px, a[1]-py) for px, py in pts) < 8
                 or min(math.hypot(b[0]-px, b[1]-py) for px, py in pts) < 8]
    else:
        stubs = stubs_norm

    junctions = list(page['junctions'])
    segs = [(a, b, True) for a, b in wires] + [(a, b, rl) for a, b, rl in stubs]

    uf = UF()
    def kp(p): return ('P', round(p[0], 2), round(p[1], 2))

    # ===== 3. Than moi seg: 2 dau mut cung net =====
    for i, (a, b, rl) in enumerate(segs):
        uf.union(kp(a), kp(b))

    ep = defaultdict(list)
    for i, (a, b, rl) in enumerate(segs):
        ep[(round(a[0]), round(a[1]))].append((i, 0))
        ep[(round(b[0]), round(b[1]))].append((i, 1))

    def near_eps(p, rad=1):
        res = []
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                res.extend(ep.get((round(p[0]) + dx, round(p[1]) + dy), []))
        return res

    # ===== 4. Endpoint trung tuyet doi (<= TOL_ENDPOINT) =====
    for i, (a, b, rl) in enumerate(segs):
        for p in (a, b):
            for j, e in near_eps(p):
                if j == i: continue
                w = segs[j][e]
                if math.hypot(w[0]-p[0], w[1]-p[1]) > TOL_ENDPOINT:
                    continue
                rj = segs[j][2]
                if not rl and not rj:
                    continue
                uf.union(kp(p), kp(w))

    # ===== 5. Junction dot: union moi seg real qua dot =====
    for jx, jy in junctions:
        hits = []
        for i, (a, b, rl) in enumerate(segs):
            if not rl: continue
            da = math.hypot(a[0]-jx, a[1]-jy)
            db = math.hypot(b[0]-jx, b[1]-jy)
            if da <= TOL_JUNCTION:
                hits.append((i, a))
            elif db <= TOL_JUNCTION:
                hits.append((i, b))
            elif _dist_ps((jx, jy), a, b) <= TOL_JUNCTION:
                if math.hypot(a[0]-jx, a[1]-jy) <= math.hypot(b[0]-jx, b[1]-jy):
                    hits.append((i, a))
                else:
                    hits.append((i, b))
        if len(hits) >= 2:
            base_p = hits[0][1]
            for _, p in hits[1:]:
                uf.union(kp(base_p), kp(p))

    # ===== 6. T-junction khong co dot -> log, khong noi =====
    dangling_tjunctions = []
    for i, (a, b, rl) in enumerate(segs):
        if not rl: continue
        for p in (a, b):
            for j, (aj, bj, rlj) in enumerate(segs):
                if j == i or not rlj: continue
                d = _dist_ps(p, aj, bj)
                if d > TOL_ENDPOINT: continue
                if math.hypot(p[0]-aj[0], p[1]-aj[1]) <= TOL_ENDPOINT: continue
                if math.hypot(p[0]-bj[0], p[1]-bj[1]) <= TOL_ENDPOINT: continue
                has_junc = any(math.hypot(jx-p[0], jy-p[1]) <= TOL_JUNCTION
                               for jx, jy in junctions)
                if not has_junc:
                    dangling_tjunctions.append((round(p[0], 1), round(p[1], 1)))

    # ===== 7. Gan pad: endpoint or mid-segment geometry =====
    attached_pads, unattached_pads, ambiguous_pads = [], [], []
    mid_seg_attach = []

    for k, (x, y) in padpos.items():
        kpad = ('PAD', k)
        cands = []
        for i, (a, b, rl) in enumerate(segs):
            da = math.hypot(a[0]-x, a[1]-y)
            db = math.hypot(b[0]-x, b[1]-y)
            d_end = min(da, db)
            if d_end <= TOL_PAD:
                cands.append((d_end, i, rl, 'end'))
                continue
            d_mid = _dist_ps((x, y), a, b)
            if d_mid <= TOL_PAD:
                seg_len = math.hypot(b[0]-a[0], b[1]-a[1])
                if seg_len > 3 * TOL_PAD:
                    cands.append((d_mid, i, rl, 'mid'))

        if not cands:
            unattached_pads.append(k)
            continue

        exact = [c for c in cands if c[3] == 'end' and c[0] < TOL_EXACT_MATCH]
        if exact:
            for d, i, rl, _where in exact:
                a, b, _ = segs[i]
                uf.union(kp(a), kpad); uf.union(kp(b), kpad)
            attached_pads.append(k)
            continue

        pool = [c for c in cands if c[3] == 'end'] or cands
        pool = [c for c in pool if c[2]] or pool
        pool.sort()
        if len(pool) >= 2 and (pool[1][0] - pool[0][0]) < TOL_TIE and pool[0][1] != pool[1][1]:
            ambiguous_pads.append(k)
            continue

        d, i, rl, where = pool[0]
        a, b, _ = segs[i]
        if where == 'mid':
            mid_seg_attach.append((k, round(x, 1), round(y, 1), round(d, 2)))
        uf.union(kp(a), kpad); uf.union(kp(b), kpad)
        attached_pads.append(k)

    # ===== 8. Nets tu attached pads =====
    net_pads = defaultdict(list)
    for k in attached_pads:
        net_pads[uf.find(('PAD', k))].append(k)

    # ===== 9. Gan label =====
    RE_REF_LIKE = re.compile(r'^[A-Z]{1,4}\d{1,3}(_[A-Z0-9]{1,4})?$', re.I)
    anchor = {}
    keep_items = list(keep.items())
    ltexts = page.get('label_texts') or texts
    for t, cx, cy, st in ltexts:
        tt = t.strip()
        if not tt or PAD_TOKEN.match(tt) or len(tt) > 24: continue
        if RE_HIDDEN.match(tt): continue
        if tt.isdigit(): continue
        if RE_REF_LIKE.match(tt) and tt.upper() in comp_pads: continue
        in_sym = any(rx0 - 2 <= cx <= rx1 + 2 and ry0 - 2 <= cy <= ry1 + 2
                     for _, (rx0, ry0, rx1, ry1) in keep_items)
        if in_sym: continue
        best = (1e9, None)
        for i, (a, b, rl) in enumerate(segs):
            if not rl: continue
            d = _dist_ps((cx, cy), a, b)
            if d < best[0]:
                best = (d, i)
        if best[1] is not None and best[0] < 16:
            anchor.setdefault(uf.find(kp(segs[best[1]][0])), []).append((tt, cx, cy))

    net_labels = {}
    for root, ls in anchor.items():
        if root in net_pads:
            names = Counter(t for t, x, y in ls)
            net_labels[root] = names.most_common(1)[0][0]

    nets, used = {}, set()
    for root, pads in net_pads.items():
        nm = net_labels.get(root)
        if not nm:
            nm = 'N_' + sorted(pads)[0].replace('.', '_')
        base, c = nm, 2
        while nm in used:
            nm = f'{base}_{c}'; c += 1
        used.add(nm)
        nets[nm] = {'pads': sorted(pads),
                    'labels': sorted({t for t, x, y in anchor.get(root, [])})}

    return {
        'wires': wires,
        'stubs': [(a, b) for a, b, _ in stubs],
        'nets': nets,
        'root_name': {r: net_labels[r] for r in net_pads if r in net_labels},
        'root_pads': {r: sorted(ps) for r, ps in net_pads.items()},
        'anchors': anchor, 'uf': uf,
        'padpos': padpos,
        'attached_pads': attached_pads,
        'unattached_pads': unattached_pads,
        'ambiguous_pads': ambiguous_pads,
        'dangling_tjunctions': dangling_tjunctions,
        'snap_moves': snap_moves,
        'snap_refused': snap_refused,
        'mid_seg_attach': mid_seg_attach,
    }
