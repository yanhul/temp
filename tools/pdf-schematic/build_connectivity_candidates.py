#!/usr/bin/env python3
"""Conservative, provenance-preserving vector wire topology candidates.

Only explicit line geometry is considered. Endpoints within tolerance and
collinear overlaps are joined geometrically. Non-collinear T contacts and
crossings remain disconnected unless a separate authority proves a junction.
This module never assigns symbols, pins, labels, or electrical net names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def _line_segments(element, evidence_id, page):
    tag = element.get("tag")
    result = []

    def add(a, b, ordinal):
        if not (isinstance(a, list) and isinstance(b, list) and len(a) == 2 and len(b) == 2):
            return
        values = tuple(float(v) for v in (*a, *b))
        if all(math.isfinite(v) for v in values) and math.dist(values[:2], values[2:]) > 1e-8:
            result.append({
                "id": f"{evidence_id}:s{ordinal}", "page": page,
                "a": [values[0], values[1]], "b": [values[2], values[3]],
                "evidence_id": evidence_id,
            })

    if tag in ("path", "line"):
        for i, segment in enumerate(element.get("segments", [])):
            if segment.get("type") == "L" and len(segment.get("points", [])) == 2:
                add(*segment["points"], i)
    elif tag in ("polyline", "polygon"):
        pts = element.get("points", [])
        for i in range(len(pts) - 1):
            add(pts[i], pts[i + 1], i)
    elif tag == "rect":
        pts = element.get("geometry", {}).get("points", [])
        for i in range(len(pts)):
            add(pts[i], pts[(i + 1) % len(pts)], i)
    return result


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _project_parameter(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2


def _point_at(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def _line_key(segment):
    """Stable grouping key for collinear segments (not a visual snap tolerance)."""
    a, b = segment["a"], segment["b"]
    length = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    if ux < 0 or (abs(ux) < 1e-12 and uy < 0):
        ux, uy = -ux, -uy
    angle = math.atan2(uy, ux)
    offset = -uy * a[0] + ux * a[1]
    # SVG coordinate transforms are deterministic; these bins absorb only
    # floating point serialization noise, not the graph endpoint tolerance.
    return (segment["page"], round(angle, 7), round(offset, 5)), (ux, uy)


def _split_collinear_overlaps(segments, tolerance):
    """Split overlaps using an interval sweep, avoiding all-pairs O(n²) scans."""
    groups = defaultdict(list)
    for segment in segments:
        key, direction = _line_key(segment)
        ux, uy = direction
        start = ux * segment["a"][0] + uy * segment["a"][1]
        end = ux * segment["b"][0] + uy * segment["b"][1]
        lo, hi = sorted((start, end))
        groups[key].append((lo, hi, segment, direction))

    cuts = {segment["id"]: [(0.0, segment["a"]), (1.0, segment["b"])]
            for segment in segments}
    overlap_pairs = []
    eps = 1e-9

    def add_cut(segment, scalar, direction):
        a, b = segment["a"], segment["b"]
        ux, uy = direction
        dx, dy = b[0] - a[0], b[1] - a[1]
        denom = ux * dx + uy * dy
        t = (scalar - (ux * a[0] + uy * a[1])) / denom
        if eps < t < 1.0 - eps:
            cuts[segment["id"]].append((t, _point_at(a, b, t)))

    for entries in groups.values():
        entries.sort(key=lambda item: (item[0], item[1], item[2]["id"]))
        active = None
        for lo, hi, segment, direction in entries:
            if active is None or lo >= active[1] - eps:
                active = (lo, hi, segment, direction)
                continue
            active_lo, active_hi, active_segment, active_direction = active
            overlap_lo, overlap_hi = lo, min(hi, active_hi)
            # A spanning-tree link is sufficient: each interval joins the
            # current connected interval component without enumerating every
            # pair of overlapping segments.
            add_cut(active_segment, overlap_lo, active_direction)
            add_cut(active_segment, overlap_hi, active_direction)
            add_cut(segment, overlap_lo, direction)
            add_cut(segment, overlap_hi, direction)
            overlap_pairs.append([active_segment["id"], segment["id"]])
            if hi > active_hi:
                active = (lo, hi, segment, direction)

    pieces = []
    for segment in segments:
        ordered = sorted(cuts[segment["id"]], key=lambda item: item[0])
        compact = []
        for t, point in ordered:
            if not compact or abs(t - compact[-1][0]) > eps:
                compact.append((t, point))
        for index, ((_, a), (_, b)) in enumerate(zip(compact, compact[1:])):
            if math.dist(a, b) > 1e-8:
                pieces.append({
                    "id": f"{segment['id']}:p{index}",
                    "source_segment_id": segment["id"],
                    "page": segment["page"],
                    "a": list(a), "b": list(b),
                    "evidence_id": segment["evidence_id"],
                })
    return pieces, sorted(overlap_pairs)

def _canonicalize_endpoints(pieces, tolerance):
    """Cluster endpoints with a spatial hash; return canonical nodes and edges."""
    points = []
    for piece in pieces:
        points.append((piece["page"], tuple(piece["a"]), piece["id"], "a"))
        points.append((piece["page"], tuple(piece["b"]), piece["id"], "b"))
    points.sort(key=lambda item: (item[0], item[1][0], item[1][1], item[2], item[3]))

    parent = list(range(len(points)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            # Stable representative independent of input traversal.
            parent[max(ra, rb)] = min(ra, rb)

    buckets = defaultdict(list)
    for i, (page, point, _, _) in enumerate(points):
        gx, gy = math.floor(point[0] / tolerance), math.floor(point[1] / tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in buckets[(page, gx + dx, gy + dy)]:
                    if math.dist(point, points[j][1]) <= tolerance:
                        union(i, j)
        buckets[(page, gx, gy)].append(i)

    groups = defaultdict(list)
    for i, item in enumerate(points):
        groups[find(i)].append((i, item))

    node_by_endpoint = {}
    nodes = []
    for members in groups.values():
        page = members[0][1][0]
        representative = min((m[1][1] for m in members), key=lambda p: (p[0], p[1]))
        node_id = "n-" + hashlib.sha256(
            f"{page}:{representative[0].hex()}:{representative[1].hex()}".encode()
        ).hexdigest()[:16]
        refs = sorted({m[1][2] for m in members})
        nodes.append({"node_id": node_id, "page": page,
                      "point": [representative[0], representative[1]],
                      "segment_refs": refs})
        for i, _ in members:
            node_by_endpoint[i] = node_id

    endpoint_index = {}
    for i, (_, _, piece_id, side) in enumerate(points):
        endpoint_index[(piece_id, side)] = node_by_endpoint[i]

    edges = []
    for piece in pieces:
        edges.append({
            "edge_id": piece["id"], "page": piece["page"],
            "from": endpoint_index[(piece["id"], "a")],
            "to": endpoint_index[(piece["id"], "b")],
            "source_segment_id": piece["source_segment_id"],
            "source_evidence": piece["evidence_id"],
            "authority": "OBSERVED_VECTOR_LINE_SEGMENT",
        })
    nodes.sort(key=lambda node: node["node_id"])
    edges.sort(key=lambda edge: edge["edge_id"])
    return nodes, edges


def _components(nodes, edges):
    adjacency = {node["node_id"]: set() for node in nodes}
    for edge in edges:
        adjacency[edge["from"]].add(edge["to"])
        adjacency[edge["to"]].add(edge["from"])
    remaining = set(adjacency)
    result = []
    while remaining:
        start = min(remaining)
        stack, found = [start], set()
        while stack:
            current = stack.pop()
            if current in found:
                continue
            found.add(current)
            stack.extend(adjacency[current] - found)
        remaining -= found
        result.append({"node_ids": sorted(found)})
    return sorted(result, key=lambda item: item["node_ids"])


def build(ir, tolerance=0.05):
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    segments = []
    for page in ir.get("pages", []):
        for evidence in page.get("evidence", []):
            if evidence.get("origin") != "normalized_svg":
                continue
            segments.extend(_line_segments(
                evidence.get("geometry", {}), evidence["evidence_id"], page["page"]
            ))

    pieces, overlap_pairs = _split_collinear_overlaps(segments, tolerance)
    nodes, edges = _canonicalize_endpoints(pieces, tolerance)
    # Graph invariants are checked before emitting a candidate graph.
    node_ids = {node["node_id"] for node in nodes}
    if any(edge["from"] not in node_ids or edge["to"] not in node_ids for edge in edges):
        raise AssertionError("edge references a non-canonical/missing node")
    return {
        "schema": "pdf-schematic-connectivity-candidates/v2",
        "status": "BLOCKED_SYMBOL_PIN_AND_JUNCTION_AUTHORITY_MISSING",
        "tolerance_pdf_points": tolerance,
        "segment_count": len(segments),
        "split_edge_count": len(edges),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "components": _components(nodes, edges),
        "collinear_overlap_pairs": sorted(overlap_pairs),
        "nodes": nodes,
        "edges": edges,
        "unknown_reasons": [
            "SYMBOL_PINS_NOT_RESOLVED",
            "T_JUNCTIONS_REQUIRE_EXPLICIT_JUNCTION_AUTHORITY",
            "CROSSINGS_ARE_NOT_CONNECTED",
            "LABEL_AND_GLOBAL_LABEL_SEMANTICS_NOT_RESOLVED",
            "NETLIST_NOT_COMPARED_WITH_NATIVE_SCHDOC",
        ],
        "policy": {
            "endpoint_contact_connects": True,
            "collinear_overlap_connects": True,
            "endpoint_to_interior_contact_connects": "ONLY_WHEN_COLLINEAR_OVERLAP",
            "non_collinear_t_junction_connects": False,
            "crossing_connects": False,
            "visual_proximity_is_not_connectivity": True,
            "pin_assignment": "NONE",
            "electrical_net_assignment": "NONE",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tolerance", type=float, default=0.05)
    args = ap.parse_args()
    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    result = build(ir, args.tolerance)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "schema", "status", "segment_count", "split_edge_count", "node_count",
        "edge_count", "unknown_reasons")}, indent=2))


if __name__ == "__main__":
    main()
