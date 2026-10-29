"""Geometric topology candidates for flattened schematic PDFs.

This module splits straight vector strokes at geometric intersections so a later
symbol/pin/net adapter can reuse the geometry. It deliberately does NOT union
crossings into electrical nets: PDFs often draw crossings without junctions.
"""
from __future__ import annotations

import math
from collections import defaultdict

EPS = 0.15


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _point_on_segment(p, a, b, tol=EPS):
    px, py = p; ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= tol * tol:
        return math.hypot(px - ax, py - ay) <= tol
    t = ((px - ax) * dx + (py - ay) * dy) / length2
    if t < -tol or t > 1 + tol:
        return False
    qx, qy = ax + max(0.0, min(1.0, t)) * dx, ay + max(0.0, min(1.0, t)) * dy
    return math.hypot(px - qx, py - qy) <= tol


def _intersection(a, b, c, d, tol=EPS):
    """Return a single intersection point; collinear overlaps are left ambiguous."""
    ax, ay = a; bx, by = b; cx, cy = c; dx, dy = d
    r = (bx - ax, by - ay); s = (dx - cx, dy - cy)
    den = _cross(*r, *s)
    qmp = (cx - ax, cy - ay)
    if abs(den) <= tol:
        # Parallel/collinear overlap cannot safely be reduced to a unique node.
        return None, "parallel_or_collinear"
    t = _cross(*qmp, *s) / den
    u = _cross(*qmp, *r) / den
    if -tol <= t <= 1 + tol and -tol <= u <= 1 + tol:
        t = min(1.0, max(0.0, t)); u = min(1.0, max(0.0, u))
        p = (ax + t * r[0], ay + t * r[1])
        on_a_end = t <= tol or t >= 1 - tol
        on_b_end = u <= tol or u >= 1 - tol
        if on_a_end and on_b_end:
            kind = "endpoint_endpoint"
        elif on_a_end or on_b_end:
            kind = "endpoint_on_segment"
        else:
            kind = "interior_crossing"
        return (round(p[0], 4), round(p[1], 4)), kind
    return None, "disjoint"


def build_geometric_topology(lines, tolerance=EPS):
    """Split vector lines at intersections and return non-electrical candidates.

    Input lines: [{"a":[x,y], "b":[x,y], ...}, ...].
    Output explicitly leaves every intersection's electrical status unknown.
    """
    normalized = []
    for index, line in enumerate(lines):
        a, b = line.get("a"), line.get("b")
        if not a or not b:
            continue
        a = (float(a[0]), float(a[1])); b = (float(b[0]), float(b[1]))
        if math.dist(a, b) <= tolerance:
            continue
        normalized.append({"source_line_index": index, "a": a, "b": b})
    cuts = {i: [item["a"], item["b"]] for i, item in enumerate(normalized)}
    intersections = []
    for i, first in enumerate(normalized):
        for j in range(i + 1, len(normalized)):
            second = normalized[j]
            p, kind = _intersection(first["a"], first["b"], second["a"], second["b"], tolerance)
            if p is None:
                continue
            cuts[i].append(p); cuts[j].append(p)
            intersections.append({
                "xy": list(p),
                "source_line_indices": [first["source_line_index"], second["source_line_index"]],
                "geometry_kind": kind,
                "electrical_status": "UNKNOWN_NO_JUNCTION_AUTHORITY",
            })

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

    # Deduplicate coincident intersections while preserving all source-line pairs.
    grouped = defaultdict(set)
    kinds = defaultdict(set)
    for item in intersections:
        key = tuple(item["xy"])
        grouped[key].update(item["source_line_indices"])
        kinds[key].add(item["geometry_kind"])
    nodes = [{
        "xy": list(xy),
        "source_line_indices": sorted(indices),
        "geometry_kinds": sorted(kinds[xy]),
        "electrical_status": "UNKNOWN_NO_JUNCTION_AUTHORITY",
    } for xy, indices in sorted(grouped.items())]
    return {
        "schema": "pdf2kicad.geometric-topology-candidates/1",
        "input_line_count": len(normalized),
        "split_edge_count": len(edges),
        "intersection_candidate_count": len(nodes),
        "edges": edges,
        "intersection_candidates": nodes,
        "electrical_connectivity": "NOT_INFERRED",
        "warning": "Geometric crossings/endpoints are not electrical junction proof.",
    }
