"""Geometric topology candidates for flattened schematic PDFs.

Splits vector strokes at segment intersections using a bounding-box sweep to avoid
quadratic all-pairs work on dense pages. This is geometry only: crossings do not
become electrical nets without independent junction/pin/label evidence.
"""
from __future__ import annotations

import math
from collections import defaultdict

EPS = 0.15


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _intersection(a, b, c, d, tol=EPS):
    """Return a unique segment intersection; collinear overlap stays unresolved."""
    ax, ay = a; bx, by = b; cx, cy = c; dx, dy = d
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    rlen = math.hypot(rx, ry); slen = math.hypot(sx, sy)
    den = _cross(rx, ry, sx, sy)
    qx, qy = cx - ax, cy - ay
    # Scale parallel tolerance by segment lengths, not coordinate units.
    if abs(den) <= 1e-10 * max(1.0, rlen * slen):
        return None, "parallel_or_collinear"
    t = _cross(qx, qy, sx, sy) / den
    u = _cross(qx, qy, rx, ry) / den
    # Convert the geometric tolerance into a parameter tolerance per segment.
    ta = tol / max(rlen, tol)
    tb = tol / max(slen, tol)
    if -ta <= t <= 1 + ta and -tb <= u <= 1 + tb:
        t = min(1.0, max(0.0, t)); u = min(1.0, max(0.0, u))
        px, py = ax + t * rx, ay + t * ry
        # Snap only to an actual endpoint within the distance tolerance.
        da = min(math.hypot(px-ax, py-ay), math.hypot(px-bx, py-by))
        db = min(math.hypot(px-cx, py-cy), math.hypot(px-dx, py-dy))
        on_a_end, on_b_end = da <= tol, db <= tol
        kind = ("endpoint_endpoint" if on_a_end and on_b_end else
                "endpoint_on_segment" if on_a_end or on_b_end else
                "interior_crossing")
        return (round(px, 4), round(py, 4)), kind
    return None, "disjoint"


def build_geometric_topology(lines, tolerance=EPS):
    """Split vector lines at geometric intersections; never emits electrical nets.

    Input lines: [{"a":[x,y], "b":[x,y], ...}, ...].
    Output preserves source indices and explicitly marks connectivity unknown.
    """
    normalized = []
    for index, line in enumerate(lines):
        a, b = line.get("a"), line.get("b")
        if not a or not b:
            continue
        a = (float(a[0]), float(a[1])); b = (float(b[0]), float(b[1]))
        if not all(math.isfinite(v) for v in (*a, *b)):
            continue
        if math.dist(a, b) <= tolerance:
            continue
        normalized.append({"source_line_index": index, "a": a, "b": b,
                           "bbox": (min(a[0],b[0]), min(a[1],b[1]),
                                    max(a[0],b[0]), max(a[1],b[1]))})

    cuts = {i: [item["a"], item["b"]] for i, item in enumerate(normalized)}
    intersections = []
    # Sweep by minimum X; only compare segments whose bounding boxes overlap.
    ordered_indices = sorted(range(len(normalized)), key=lambda i: normalized[i]["bbox"][0])
    active = []
    candidate_pair_count = 0
    for i in ordered_indices:
        current = normalized[i]
        xmin, ymin, xmax, ymax = current["bbox"]
        active = [j for j in active if normalized[j]["bbox"][2] >= xmin - tolerance]
        for j in active:
            other = normalized[j]
            _, oymin, _, oymax = other["bbox"]
            if oymax < ymin - tolerance or ymax < oymin - tolerance:
                continue
            candidate_pair_count += 1
            p, kind = _intersection(other["a"], other["b"], current["a"], current["b"], tolerance)
            if p is None:
                continue
            cuts[j].append(p); cuts[i].append(p)
            intersections.append({
                "xy": list(p),
                "source_line_indices": sorted([other["source_line_index"], current["source_line_index"]]),
                "geometry_kind": kind,
                "electrical_status": "UNKNOWN_NO_JUNCTION_AUTHORITY",
            })
        active.append(i)

    edges = []
    for i, line in enumerate(normalized):
        a, b = line["a"], line["b"]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        unique = {}
        for p in cuts[i]:
            t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
            unique[round(max(0.0, min(1.0, t)), 8)] = (p[0], p[1])
        ordered = sorted(unique.items())
        for (_, p), (_, q) in zip(ordered, ordered[1:]):
            if math.dist(p, q) <= tolerance:
                continue
            edges.append({
                "a": [round(p[0], 4), round(p[1], 4)],
                "b": [round(q[0], 4), round(q[1], 4)],
                "source_line_index": line["source_line_index"],
                "electrical_status": "GEOMETRY_ONLY_NOT_A_NET",
            })

    grouped = defaultdict(set)
    kinds = defaultdict(set)
    for item in intersections:
        key = tuple(item["xy"])
        grouped[key].update(item["source_line_indices"])
        kinds[key].add(item["geometry_kind"])
    nodes = [{
        "xy": list(xy), "source_line_indices": sorted(indices),
        "geometry_kinds": sorted(kinds[xy]),
        "electrical_status": "UNKNOWN_NO_JUNCTION_AUTHORITY",
    } for xy, indices in sorted(grouped.items())]
    return {
        "schema": "pdf2kicad.geometric-topology-candidates/1",
        "input_line_count": len(normalized),
        "candidate_pair_count": candidate_pair_count,
        "split_edge_count": len(edges),
        "intersection_candidate_count": len(nodes),
        "edges": edges, "intersection_candidates": nodes,
        "electrical_connectivity": "NOT_INFERRED",
        "warning": "Geometric crossings/endpoints are not electrical junction proof.",
    }
