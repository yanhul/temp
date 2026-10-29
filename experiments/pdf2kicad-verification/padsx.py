#!/usr/bin/env python3
"""Giai doan B: giai ma ban ghi pad an 'PI<REF>0<PAD>' — GENERIC, strict.

Thay doi so voi ban truoc:
  - BO hoan toan voting mu (_cluster eps=25 + dem phieu).
  - Record co >=2 candidate refs ngang nhau -> AMBIGUOUS, khong doan.
  - Chi chon khi margin RO RANG:
      * contiguity pad-score hon >=5 diem, HOAC
      * khoang cach toi CO record hon >=15pt.
  - Tra ve (padpos, refs_found, refs_unseen, unresolved, ambiguous).
"""
import re, math
from collections import defaultdict, Counter

RE_REF_CORE = re.compile(r'^[A-Za-z]{1,4}[0-9]{1,3}(_[A-Za-z0-9]{1,4})?$')
RE_WORD_REF = re.compile(r'^[A-Za-z]{1,4}[0-9]{1,3}(_[A-Za-z0-9]{1,4})?$')


def find_visible_refs(texts):
    """co_pos[ref] = LIST cac vi tri. Dung min() khi do khoang cach."""
    refs = set()
    co_exact, co_stripped = defaultdict(list), defaultdict(list)
    for t, x, y, st in texts:
        for w in t.split():
            wu = w.upper()
            if wu.startswith('CO') and len(wu) <= 10:
                core = wu[2:]
                if RE_WORD_REF.match(core):
                    refs.add(core)
                    co_exact[core].append((x, y))
                if core.endswith('0'):
                    s = core[:-1]
                    if RE_WORD_REF.match(s):
                        refs.add(s)
                        co_stripped[s].append((x, y))
            elif len(wu) <= 7 and RE_WORD_REF.match(wu):
                refs.add(wu)
                co_exact[wu].append((x, y))
    co_pos = defaultdict(list, {k: list(v) for k, v in co_stripped.items()})
    for k, v in co_exact.items():
        co_pos[k] = co_pos[k] + list(v)
    return refs, co_pos


def _pads_from_rest(rest):
    if not rest:
        return None
    if rest.isdigit():
        n = int(rest)
        return (str(n),) if 1 <= n <= 99 else None
    segs = [s for s in rest.split('0') if s]
    if not segs:
        return None
    pads = []
    for s in segs:
        if s.isdigit():
            n = int(s)
            if n < 1 or n > 99:
                return None
            pads.append(str(n))
        elif re.match(r'^[A-Za-z]{1,3}[0-9]{1,3}$', s) or s.upper() == 'EPAD':
            pads.append(s.upper())
        else:
            return None
    return tuple(pads)


def _ref_splits(content):
    out = []
    for L in range(2, min(len(content), 9) + 1):
        ref, rest = content[:L], content[L:]
        if not RE_REF_CORE.match(ref):
            continue
        if not rest.startswith('0'):
            continue
        out.append((ref, rest))
    return out


def parse_pad_records(texts, tokens=None):
    """Use char-level token positions when available; otherwise fall back to texts."""
    if tokens is None:
        tokens = []
        for t, cx, cy, st in texts:
            for w in t.split():
                if w:
                    tokens.append((w, cx, cy, None))

    records = []
    for idx, (w, cx, cy, char_pos) in enumerate(tokens):
        if 'PI' not in w:
            continue
        for m in re.finditer('PI', w):
            i = m.start()
            if char_pos is not None and i < len(char_pos):
                px = char_pos[i][1]
                py = cy
            else:
                px, py = cx, cy
            content = w[i + 2:].split('PI')[0]
            if not content:
                continue
            cands = []
            for ref, rest in _ref_splits(content):
                pads = _pads_from_rest(rest[1:])
                if pads:
                    cands.append((ref.upper(), pads))
            if not cands:
                nxt = tokens[idx + 1][0] if idx + 1 < len(tokens) else ''
                if nxt and not nxt.startswith(('PI', 'CO')):
                    for ref, rest in _ref_splits(content):
                        if rest == '0':
                            pads = _pads_from_rest(nxt.split('PI')[0])
                            if pads:
                                cands.append((ref.upper(), pads))
            if not cands:
                continue
            records.append((cands, (px, py), False))
    return records


def _contiguity_score(pads):
    nums = defaultdict(list)
    for p in pads:
        if p.isdigit():
            nums['n'].append(int(p))
        else:
            m = re.match(r'^([A-Z]+)([0-9]+)$', p)
            if m:
                nums[m.group(1)].append(int(m.group(2)))
    score = 0
    for grp, vals in nums.items():
        s = sorted(set(vals))
        score += len(s) * 10
        if s and s[0] == 1:
            score += 5
        if len(s) > 1:
            score -= (s[-1] - s[0] + 1 - len(s)) * 4
    return score


def decode_pads(texts, verbose=True, tokens=None):
    records = parse_pad_records(texts, tokens=tokens)
    visible, co_pos = find_visible_refs(texts)

    assign = {}
    ambiguous = []
    unresolved = []

    for i, (cands, (cx, cy), standalone) in enumerate(records):
        vis = [c for c in cands if c[0] in visible]
        pool = vis if vis else cands
        if not pool:
            unresolved.append((i, cands))
            continue
        if len(pool) == 1:
            assign[i] = pool[0]
            continue

        scored = []
        for ref, pads in pool:
            sc = _contiguity_score(pads)
            ps = co_pos.get(ref) or []
            dco = min((math.hypot(p[0] - cx, p[1] - cy) for p in ps), default=1e9)
            scored.append((sc, -dco, -len(ref), ref, pads))
        scored.sort(reverse=True)

        if scored[0][0] > scored[1][0] + 5:
            assign[i] = (scored[0][3], scored[0][4])
            continue
        d0 = -scored[0][1]
        d1 = -scored[1][1]
        if d1 - d0 > 15:
            assign[i] = (scored[0][3], scored[0][4])
            continue

        ambiguous.append((i, pool, (round(cx, 1), round(cy, 1))))

    occ = defaultdict(list)
    for i, (ref, pads) in assign.items():
        for p in pads:
            occ[f'{ref}.{p}'].append(records[i][1])
    padpos = {}
    for k, ps in occ.items():
        cnt = Counter((round(x, 1), round(y, 1)) for x, y in ps)
        padpos[k] = cnt.most_common(1)[0][0]

    refs_found = {k.split('.')[0] for k in padpos}
    return padpos, refs_found, visible - refs_found, unresolved, ambiguous
